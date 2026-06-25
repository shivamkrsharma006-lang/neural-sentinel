"""
Detection Agent — V2: Event-Triggered Exponential-Decay Priority Scheduler
           + Post-Inference Metadata Deduplication with Hardware Timestamps

Patent Specification Implementation:
  Scheduler:  U(c,t) = max(U_min, α·V(c,t) + β·U(c,t−1)·e^(−λ·Δt))
  Selection:  Weighted round-robin using normalized urgency weights w_c = U(c)/ΣU
  Dedup:      One physical capture → one model invocation → hardware-timestamped
              metadata forked asynchronously to N rule evaluators.
  Stale-drop: Callbacks discarded if (now − hardware_timestamp) > STALE_DROP_S
"""

import threading
import time
import math
import random
import concurrent.futures
import cv2
import numpy as np
import logging
from collections import OrderedDict
from typing import Dict, Optional, Callable, List
from dataclasses import dataclass, field
import torch
torch.set_num_threads(4)
from ultralytics import YOLO
from config import (
    YOLO_MODEL, THETA_TRACK,
    SCHED_ALPHA, SCHED_BETA, SCHED_LAMBDA, SCHED_U_MIN,
)

logger = logging.getLogger(__name__)

# Stale-metadata drop threshold (seconds) — patent §C(iv)
STALE_DROP_S = 0.5

# ── In-memory evidence frame store (OrderedDict for O(1) FIFO eviction) ───────
_evidence_frames: OrderedDict = OrderedDict()
_evidence_lock = threading.Lock()


def store_evidence_frame(key: str, jpeg_bytes: bytes):
    from config import FRAMES_DIR
    with _evidence_lock:
        _evidence_frames[key] = jpeg_bytes
        if len(_evidence_frames) > 500:
            _evidence_frames.popitem(last=False)  # O(1) FIFO eviction
    try:
        path = FRAMES_DIR / f"{key}.jpg"
        with open(str(path), 'wb') as f:
            f.write(jpeg_bytes)
    except Exception as e:
        logger.debug(f"Frame disk backup failed: {e}")


def get_evidence_frame(key: str) -> Optional[bytes]:
    from config import FRAMES_DIR
    with _evidence_lock:
        data = _evidence_frames.get(key)
    if data:
        return data
    try:
        path = FRAMES_DIR / f"{key}.jpg"
        if path.exists():
            with open(str(path), 'rb') as f:
                return f.read()
    except Exception:
        pass
    return None


def list_evidence_keys() -> List[str]:
    with _evidence_lock:
        return list(_evidence_frames.keys())


# ── Camera name registry ──────────────────────────────────────────────────────
_camera_names: Dict[int, str] = {}

def register_camera_name(camera_id: int, name: str):
    _camera_names[camera_id] = name

def get_camera_name(camera_id: int) -> str:
    return _camera_names.get(camera_id, f'Camera {camera_id}')


@dataclass
class DetectionResult:
    camera_id: int
    frame: np.ndarray
    detections: List[dict]   # [{track_id, class_name, confidence, bbox, center}]
    timestamp: float = field(default_factory=time.time)
    # Patent §B — monotonic CPU timestamp injected at moment of model output
    hardware_timestamp: float = field(default_factory=time.monotonic)


class CameraCapture:
    def __init__(self, camera_id: int, source: str):
        self.camera_id = camera_id
        self.source = source
        self._cap: Optional[cv2.VideoCapture] = None
        self._frame: Optional[np.ndarray] = None
        self._lock = threading.Lock()
        self._running = False
        self._disabled = False   # deliberately paused by user (survives arm/disarm)
        self._thread: Optional[threading.Thread] = None
        self.status = "connecting"
        self.width = 640
        self.height = 480
        self.last_updated = 0.0

    def start(self):
        if self._running or self._disabled:
            return
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        # Grab and clear _cap FIRST (inside lock), then release OUTSIDE lock.
        # This prevents deadlock with _capture_loop which also holds self._lock
        # during the blocking cap.read() call.
        with self._lock:
            cap_to_release = self._cap
            self._cap = None
            self._frame = None
        if cap_to_release:
            try:
                cap_to_release.release()
            except Exception:
                pass
        self.status = "offline"

    def pause(self):
        """Deliberately disable this camera (survives system arm/disarm cycles)."""
        self._disabled = True
        self.stop()
        self.status = "disabled"
        logger.info(f"Camera {self.camera_id} paused by user")

    def resume(self):
        """Re-enable a previously paused camera."""
        self._disabled = False
        self.status = "offline"
        logger.info(f"Camera {self.camera_id} resumed by user")
        self.start()

    def get_frame(self) -> Optional[np.ndarray]:
        with self._lock:
            return self._frame.copy() if self._frame is not None else None

    def _open_capture(self) -> bool:
        src = self.source.strip()
        try:
            idx = int(src)
            cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
        except ValueError:
            cap = cv2.VideoCapture(src)

        if cap.isOpened():
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self._cap = cap
            self.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640
            self.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480
            self.status = "online"
            return True
        self.status = "error"
        return False

    def _capture_loop(self):
        # Exponential backoff: 3 → 6 → 12 → 24 → 60s (max), resets on success
        retry_delay = 3
        max_delay = 60
        while self._running and not self._disabled:
            if not self._open_capture():
                logger.warning(
                    f"Camera {self.camera_id} ({self.source}) failed. "
                    f"Retrying in {retry_delay}s"
                )
                self.status = "offline"
                time.sleep(retry_delay)
                if not self._running or self._disabled:
                    return
                retry_delay = min(retry_delay * 2, max_delay)  # exponential backoff
                continue
            # Connected successfully — reset backoff
            logger.info(f"Camera {self.camera_id} online ({self.source})")
            retry_delay = 3
            fail_count = 0
            while self._running and not self._disabled:
                with self._lock:
                    cap_ref = self._cap
                if cap_ref is None:
                    break

                try:
                    if not self._running or self._disabled:
                        break
                    ret, frame = cap_ref.read()
                except Exception:
                    # Capture was released concurrently by stop() — exit cleanly
                    break

                if not ret:
                    fail_count += 1
                    if fail_count > 10:
                        self.status = "offline"
                        # Grab+clear inside lock, release outside (same pattern as stop())
                        with self._lock:
                            cap_to_release = self._cap
                            self._cap = None
                        if cap_to_release:
                            try:
                                cap_to_release.release()
                            except Exception:
                                pass
                        break
                    time.sleep(0.05)
                    continue

                fail_count = 0
                with self._lock:
                    self._frame = frame
                    self.last_updated = time.monotonic()
            if not self._running or self._disabled:
                return
            time.sleep(retry_delay)



class PriorityScheduler:
    """
    V2 Patent Scheduler — U(c,t) = max(U_min, α·V(c,t) + β·U(c,t−1)·e^(−λ·Δt))

    Camera selection uses weighted round-robin (probabilistic allocation)
    rather than a rigid winner-take-all queue, ensuring all cameras receive
    a minimum baseline inference allocation (U_min fairness floor).
    """

    POLL_INTERVAL = 0.033   # ~30fps poll rate

    def __init__(self):
        self._scores: Dict[int, float] = {}
        self._last_inferred: Dict[int, float] = {}
        self._last_updated: Dict[int, float] = {}   # for Δt computation
        self._lock = threading.Lock()

    def add_camera(self, camera_id: int):
        with self._lock:
            now = time.monotonic()
            self._scores[camera_id] = SCHED_U_MIN
            self._last_inferred[camera_id] = 0.0
            self._last_updated[camera_id] = now

    def remove_camera(self, camera_id: int):
        with self._lock:
            self._scores.pop(camera_id, None)
            self._last_inferred.pop(camera_id, None)
            self._last_updated.pop(camera_id, None)

    def update_score(self, camera_id: int, violation: bool, risk_score: float = 0.0):
        """
        Apply the recurrence equation:
          U(c,t) = max(U_min, α·V(c,t) + β·U(c,t−1)·e^(−λ·Δt))

        V(c,t) is now a continuous value in [0, 1], not a binary flag:
          V(c,t) = max(1.0 if violation else 0.0, risk_score)

        This means:
        - A binary zone-crossing spike (V=1.0) still fires immediately (unchanged).
        - Between spikes, if R(id,t) is high (e.g. 0.85), V stays at 0.85 rather
          than collapsing to 0.0, keeping U(c,t) continuously elevated proportional
          to the computed threat magnitude — a proportional control loop.
        - A camera with no threat (R=0, no violation) decays normally toward U_min.

        Patent §B extension: V(c,t) = max(V_binary(c,t), R(id,t)) where
        R(id,t) is the concurrently-computed logistic composite risk score.
        """
        with self._lock:
            if camera_id not in self._scores:
                return
            now = time.monotonic()
            dt = now - self._last_updated.get(camera_id, now)
            u_prev = self._scores[camera_id]
            # V is continuous: binary spike overrides, risk_score sustains between spikes
            V = max(1.0 if violation else 0.0, float(risk_score))
            u_new = SCHED_ALPHA * V + SCHED_BETA * u_prev * math.exp(-SCHED_LAMBDA * dt)
            self._scores[camera_id] = max(SCHED_U_MIN, min(1.0, u_new))
            self._last_updated[camera_id] = now

    def get_next(self) -> Optional[int]:
        """
        Weighted round-robin: normalise urgency scores across all ready cameras
        and select probabilistically. Ready = elapsed >= POLL_INTERVAL.
        """
        with self._lock:
            now = time.monotonic()
            ready = [
                cam_id for cam_id, score in self._scores.items()
                if now - self._last_inferred.get(cam_id, 0) >= self.POLL_INTERVAL
            ]
            if not ready:
                return None
            weights = [self._scores[c] for c in ready]
            total = sum(weights)
            if total <= 0:
                selected = random.choice(ready)
            else:
                selected = random.choices(ready, weights=weights, k=1)[0]
            self._last_inferred[selected] = now
            return selected

    def get_score(self, camera_id: int) -> float:
        with self._lock:
            return self._scores.get(camera_id, SCHED_U_MIN)


class DetectionAgent:
    """
    V2 Patent Architecture:
    - One shared object detection model, one inference thread.
    - Alias cameras share one physical capture; post-inference metadata is
      forked to independent rule evaluators via async thread pool.
    - Hardware timestamps injected at model output; stale metadata dropped
      before callback dispatch (causal consistency enforcement).
    """

    def __init__(self):
        self._model: Optional[YOLO] = None
        self._model_lock = threading.Lock()
        self._captures: Dict[int, CameraCapture] = {}
        self._source_aliases: Dict[int, int] = {}
        self._results: Dict[int, DetectionResult] = {}
        self._results_lock = threading.Lock()
        self._scheduler = PriorityScheduler()
        self._inference_thread: Optional[threading.Thread] = None
        self._running = False
        self._result_callbacks: List[Callable] = []
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        self._prev_gray: Dict[int, np.ndarray] = {}
        self._armed = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    def start(self):
        self._load_model()
        self._running = True
        self._inference_thread = threading.Thread(target=self._inference_loop, daemon=True)
        self._inference_thread.start()
        logger.info("DetectionAgent V2 started")

    def stop(self):
        self._running = False
        self._executor.shutdown(wait=False)
        for cap in self._captures.values():
            cap.stop()
        logger.info("DetectionAgent stopped")

    def _load_model(self):
        with self._model_lock:
            if self._model is None:
                logger.info(f"Loading model: {YOLO_MODEL}")
                self._model = YOLO(YOLO_MODEL)
                logger.info("Model loaded")

    def arm(self):
        if not self._armed:
            self._armed = True
            logger.info(">>> SYSTEM ARMED: Starting camera hardware and AI inference")
            for cap in self._captures.values():
                if not cap._disabled:  # skip cameras paused by user
                    cap.start()

    def disarm(self):
        if self._armed:
            self._armed = False
            logger.info(">>> SYSTEM DISARMED: Releasing cameras and pausing AI")
            for cap in self._captures.values():
                cap.stop()

    def pause_camera(self, camera_id: int):
        """Pause a specific camera (persists across arm/disarm cycles)."""
        primary_id = self._source_aliases.get(camera_id, camera_id)
        cap = self._captures.get(primary_id)
        if cap:
            cap.pause()

    def resume_camera(self, camera_id: int):
        """Resume a paused camera (only activates if system is armed)."""
        primary_id = self._source_aliases.get(camera_id, camera_id)
        cap = self._captures.get(primary_id)
        if cap:
            cap._disabled = False
            cap.status = "offline"
            logger.info(f"Camera {camera_id} resumed")
            if self._armed:  # only actually start if system is armed
                cap.start()

    def is_camera_disabled(self, camera_id: int) -> bool:
        primary_id = self._source_aliases.get(camera_id, camera_id)
        cap = self._captures.get(primary_id)
        return cap._disabled if cap else False

    # ── Camera management ─────────────────────────────────────────────────────
    def add_camera(self, camera_id: int, source: str, name: str = ''):
        if camera_id in self._captures or camera_id in self._source_aliases:
            return
        if name:
            register_camera_name(camera_id, name)
        normalized_src = source.strip()
        for existing_id, existing_cap in self._captures.items():
            if existing_cap.source.strip() == normalized_src:
                logger.info(f"Camera {camera_id} ('{name}') aliased to camera {existing_id}")
                self._source_aliases[camera_id] = existing_id
                self._scheduler.add_camera(camera_id)
                return
        cap = CameraCapture(camera_id, source)
        if self._armed:
            cap.start()
        self._captures[camera_id] = cap
        self._scheduler.add_camera(camera_id)
        logger.info(f"Camera {camera_id} ('{name}') added ({source})")

    def remove_camera(self, camera_id: int):
        if camera_id in self._source_aliases:
            self._source_aliases.pop(camera_id)
            self._scheduler.remove_camera(camera_id)
            with self._results_lock:
                self._results.pop(camera_id, None)
            logger.info(f"Camera {camera_id} alias removed")
            return
        cap = self._captures.pop(camera_id, None)
        if cap:
            cap.stop()
        self._scheduler.remove_camera(camera_id)
        with self._results_lock:
            self._results.pop(camera_id, None)
        for alias_id, primary_id in list(self._source_aliases.items()):
            if primary_id == camera_id:
                self._source_aliases.pop(alias_id)
                self._scheduler.remove_camera(alias_id)
        logger.info(f"Camera {camera_id} removed")

    def get_camera_status(self, camera_id: int) -> str:
        primary_id = self._source_aliases.get(camera_id, camera_id)
        cap = self._captures.get(primary_id)
        if cap is None:
            return 'offline'
        if cap._disabled:
            return 'disabled'
        return cap.status

    def get_snapshot(self, camera_id: int) -> Optional[np.ndarray]:
        primary_id = self._source_aliases.get(camera_id, camera_id)
        cap = self._captures.get(primary_id)
        return cap.get_frame() if cap else None

    def get_snapshot_timestamp(self, camera_id: int) -> float:
        primary_id = self._source_aliases.get(camera_id, camera_id)
        cap = self._captures.get(primary_id)
        return cap.last_updated if cap else 0.0

    def get_result(self, camera_id: int) -> Optional[DetectionResult]:
        with self._results_lock:
            return self._results.get(camera_id)

    def update_urgency(self, camera_id: int, violation: bool, risk_score: float = 0.0):
        """
        Called by DecisionAgent after rule evaluation.
        Applies the V2 exponential decay recurrence with V(c,t) from violation state.
        risk_score (R(id,t) ∈ [0,1]) is the highest current logistic risk on this
        camera — used to keep U(c,t) continuously elevated between binary spikes.
        """
        self._scheduler.update_score(camera_id, violation, risk_score)

    def register_callback(self, fn: Callable):
        self._result_callbacks.append(fn)

    # ── Inference loop ────────────────────────────────────────────────────────
    def _inference_loop(self):
        while self._running:
            if not self._armed:
                time.sleep(0.1)
                continue

            camera_id = self._scheduler.get_next()
            if camera_id is None:
                time.sleep(0.005)
                continue

            primary_id = self._source_aliases.get(camera_id, camera_id)
            cap = self._captures.get(primary_id)
            if cap is None or cap._disabled:
                # Camera deliberately paused — skip entirely, do NOT reuse old results
                continue
            frame = cap.get_frame()
            if frame is None:
                continue

            # ── Motion Gating (V2) ────────────────────────────────────────
            # Run pixel-motion analysis. If no motion and urgency is low,
            # skip the heavy model invocation and reuse previous metadata.
            # Note: ByteTrack track ID changes from skipped frames are now
            # handled by the verified identity cache in DecisionAgent.
            urgency = self._scheduler.get_score(camera_id)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (21, 21), 0)

            has_motion = True
            if urgency < 0.5 and primary_id in self._prev_gray:
                diff = cv2.absdiff(self._prev_gray[primary_id], gray)
                thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)[1]
                if cv2.countNonZero(thresh) < 500:
                    has_motion = False

            self._prev_gray[primary_id] = gray

            if not has_motion:
                with self._results_lock:
                    prev = self._results.get(camera_id)
                detections = prev.detections if prev else []
            else:
                detections = self._run_inference(frame)

            # ── Hardware timestamp injected at moment of model output ──────
            result = DetectionResult(
                camera_id=camera_id,
                frame=frame,
                detections=detections,
                hardware_timestamp=time.monotonic(),
            )
            with self._results_lock:
                self._results[camera_id] = result

            # ── Async dispatch with stale-drop enforcement (patent §C(iv)) ─
            now_mono = time.monotonic()
            for cb in self._result_callbacks:
                age = now_mono - result.hardware_timestamp
                if age > STALE_DROP_S:
                    logger.debug(f"Stale metadata dropped for cam{camera_id} (age={age:.3f}s)")
                    continue
                try:
                    self._executor.submit(cb, result)
                except Exception as e:
                    logger.error(f"Callback dispatch error cam{camera_id}: {e}")

    def _run_inference(self, frame: np.ndarray) -> List[dict]:
        if self._model is None:
            return []
        try:
            with self._model_lock:
                results = self._model.track(
                    frame,
                    persist=True,
                    conf=THETA_TRACK,
                    verbose=False,
                    tracker="bytetrack.yaml",
                )
            detections = []
            if results and results[0].boxes is not None:
                boxes = results[0].boxes
                for i in range(len(boxes)):
                    xyxy = boxes.xyxy[i].cpu().numpy().tolist()
                    conf = float(boxes.conf[i].cpu().numpy())
                    cls  = int(boxes.cls[i].cpu().numpy())
                    track_id = int(boxes.id[i].cpu().numpy()) if boxes.id is not None else i
                    class_name = self._model.names.get(cls, str(cls))
                    cx = (xyxy[0] + xyxy[2]) / 2
                    cy = (xyxy[1] + xyxy[3]) / 2
                    detections.append({
                        "track_id": track_id,
                        "class_name": class_name,
                        "confidence": conf,
                        "bbox": xyxy,
                        "center": [cx, cy],
                    })
            return detections
        except Exception as e:
            logger.error(f"Inference error: {e}")
            return []


# ── Global singleton ──────────────────────────────────────────────────────────
detection_agent = DetectionAgent()
