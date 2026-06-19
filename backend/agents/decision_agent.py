"""
Decision Agent — V2: Logistic Temporal Risk Accumulation + Biometric A(id) Injection

Patent Specification Implementation:
  FSM:        IDLE → ENTERING → PRESENT → LOITERING → THREAT
              THREAT transition gated by θ_alert (two-tiered confidence gate)

  Risk:       S(id,t) = Σ C_i · (1−A(id)) · e^(γ·(t−t_i))
              R(id,t) = 1 / (1 + e^(−k·(S(id,t)−0.5)))

  Biometric:  On face match → A(id) = 1.0 injected into integral,
              collapsing S to 0 and decaying R below threshold mid-tracking
              without resetting the FSM or stopping geometric zone tracking.

  Urgency:    Reports violation state back to DetectionAgent after each
              evaluation cycle, closing the behavioral feedback loop.
"""

import time
import math
import json
import logging
import numpy as np
import cv2
from enum import Enum
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from agents.detection_agent import DetectionResult, detection_agent
from utils.geometry import (
    point_in_polygon, detect_line_crossing, normalize_points,
    compute_bottom_center, compute_centroid, is_armed, pixel_distance
)
from utils import face_utils
from config import (
    FACE_MATCH_THRESHOLD,
    THETA_ALERT,
    RISK_GAMMA, RISK_K, RISK_THRESHOLD,
)

logger = logging.getLogger(__name__)


class FSMState(str, Enum):
    IDLE     = "IDLE"
    ENTERING = "ENTERING"
    PRESENT  = "PRESENT"
    LOITERING= "LOITERING"
    THREAT   = "THREAT"


class RiskLevel(str, Enum):
    LOW      = "LOW"
    MEDIUM   = "MEDIUM"
    HIGH     = "HIGH"
    CRITICAL = "CRITICAL"


def score_to_level(score: float) -> str:
    if score < 0.3:
        return RiskLevel.LOW
    elif score < 0.55:
        return RiskLevel.MEDIUM
    elif score < 0.75:
        return RiskLevel.HIGH
    else:
        return RiskLevel.CRITICAL


@dataclass
class ObjectState:
    track_id: int
    camera_id: int
    fsm_state: FSMState = FSMState.IDLE
    zone_id: Optional[int] = None
    zone_name: str = ""
    first_entry_time: Optional[float] = None
    last_seen: float = field(default_factory=time.time)
    prev_center: Optional[Tuple[float, float]] = None
    identity: str = "UNKNOWN"
    auth_score: float = 0.0
    A_id: float = 0.0          # biometric authorization tensor (patent §F)
    face_checked: bool = False
    violation_type: Optional[str] = None
    # V2 — severity accumulator S(id,t) (continuous temporal integral)
    severity_sum: float = 0.0
    last_observation_time: float = field(default_factory=time.time)
    in_violation: bool = False  # tracks whether currently in any zone violation
    # Per-track event cooldown — prevents DB/alert flooding while in THREAT state
    last_event_time: float = 0.0
    # Throttle heavy face extraction
    last_face_check_time: float = 0.0
    # Multi-frame embedding buffer — accumulate N embeddings and average for robustness
    embedding_buffer: list = field(default_factory=list)  # List[np.ndarray]
    face_check_count: int = 0
    # ── Threat Hysteresis (patent §D extension) ───────────────────────────────
    # When an object briefly exits a zone, we do NOT immediately reset the FSM
    # and severity_sum. Instead we record the exit time and wait HYSTERESIS_SECONDS.
    # Only if the object is still outside the zone after that window do we reset.
    # This prevents adversarial severity-reset exploits via brief zone exits.
    zone_exit_time: Optional[float] = None   # wall-clock time of most recent zone exit
    # Highest R(id,t) computed for this track — fed back to scheduler as V(c,t)
    peak_risk_score: float = 0.0


@dataclass
class ViolationEvent:
    camera_id: int
    zone_id: int
    zone_name: str
    track_id: int
    object_class: str
    confidence: float
    risk_score: float
    risk_level: str
    identity: str
    auth_score: float
    violation_type: str
    frame: np.ndarray
    bbox: List[float]
    timestamp: float = field(default_factory=time.time)


class DecisionAgent:
    """
    V2 Decision Agent — evaluates detections against zone rules, maintains
    per-object FSMs with logistic temporal risk accumulation, and closes the
    behavioral feedback loop by reporting violation state back to the scheduler.
    """

    LOITERING_CLEANUP_SECONDS = 5.0
    EVENT_COOLDOWN_S = 60.0
    # ── Threat Hysteresis ─────────────────────────────────────────────────────
    # Grace period (seconds) before a zone-exited object's FSM and severity_sum
    # are reset. Prevents adversarial severity-reset via brief zone boundary exits
    # and handles YOLO track loss during partial occlusion (1-3 frame dropout).
    HYSTERESIS_SECONDS = 3.0

    def __init__(self):
        self._zones: Dict[int, List[dict]] = {}
        self._states: Dict[Tuple[int, int], ObjectState] = {}
        self._enrolled_faces: List[Tuple[str, np.ndarray]] = []
        self._violation_callbacks = []
        self._frame_dims: Dict[int, Tuple[int, int]] = {}

    # ── Zone management ───────────────────────────────────────────────────────
    def set_zones(self, camera_id: int, zones: List[dict]):
        self._zones[camera_id] = zones

    def reload_zones(self, camera_id: int, zones: List[dict]):
        self._zones[camera_id] = zones

    # ── Face enrollment ───────────────────────────────────────────────────────
    def set_enrolled_faces(self, faces: List[Tuple[str, np.ndarray]]):
        self._enrolled_faces = faces

    # ── Callback registration ──────────────────────────────────────────────────
    def register_callback(self, fn):
        self._violation_callbacks.append(fn)

    # ── Main processing ───────────────────────────────────────────────────────
    def process(self, result: DetectionResult):
        """
        Process one DetectionResult. After evaluating all detections and zones,
        reports violation state back to the DetectionAgent's scheduler to close
        the behavioral feedback loop (patent Claim 1d).
        """
        camera_id = result.camera_id
        frame = result.frame
        h, w = frame.shape[:2]
        self._frame_dims[camera_id] = (w, h)
        zones = self._zones.get(camera_id, [])

        now = time.time()
        active_track_ids = set()
        camera_in_violation = False
        camera_peak_risk = 0.0  # highest R(id,t) on this camera this cycle

        for det in result.detections:
            track_id = det["track_id"]
            if track_id < 0:
                continue
            active_track_ids.add(track_id)
            key = (camera_id, track_id)
            state = self._states.setdefault(
                key, ObjectState(track_id=track_id, camera_id=camera_id)
            )
            state.last_seen = now
            center = tuple(det["center"])
            bbox = det["bbox"]

            det_in_violation = False
            for zone in zones:
                if not zone.get("active", True):
                    continue
                config = json.loads(zone.get("config_json", "{}"))
                if not is_armed(config):
                    continue
                zone_id   = zone["id"]
                zone_type = zone["zone_type"]
                points    = json.loads(zone["points_json"])
                pixel_pts = normalize_points(points, w, h)
                obj_class = det["class_name"]
                class_filter = config.get("class_filter", "")
                if class_filter and class_filter != "all" and obj_class != class_filter:
                    continue

                if zone_type == "polygon":
                    violated = self._eval_polygon(
                        state, det, zone, zone_id, pixel_pts, config, center, frame, now
                    )
                elif zone_type == "tripwire":
                    violated = (len(pixel_pts) >= 2 and self._eval_tripwire(
                        state, det, zone, zone_id, pixel_pts, config, center, frame, now
                    ))
                elif zone_type == "speedgate":
                    violated = (len(pixel_pts) >= 2 and self._eval_speedgate(
                        state, det, zone, zone_id, pixel_pts, config, center, frame, now
                    ))
                else:
                    violated = False

                if violated:
                    det_in_violation = True

            if det_in_violation:
                camera_in_violation = True

            # Track the highest risk score on this camera for proportional V(c,t)
            camera_peak_risk = max(camera_peak_risk, state.peak_risk_score)

            state.in_violation = det_in_violation
            state.prev_center = center
            state.last_observation_time = now

        # ── Close behavioral feedback loop — report violation state AND risk score
        # to scheduler, enabling proportional V(c,t) modulation (patent §B extension)
        detection_agent.update_urgency(camera_id, camera_in_violation, camera_peak_risk)

        # ── Cleanup stale states ──────────────────────────────────────────────
        stale = [k for k, s in self._states.items()
                 if k[0] == camera_id and now - s.last_seen > self.LOITERING_CLEANUP_SECONDS]
        for k in stale:
            del self._states[k]

    # ── Zone evaluators ───────────────────────────────────────────────────────
    def _eval_polygon(self, state, det, zone, zone_id, pixel_pts, config,
                      center, frame, now) -> bool:
        inside = point_in_polygon(center, pixel_pts)
        dwell_threshold = config.get("dwell_time", 5.0)

        if inside:
            if state.fsm_state in (FSMState.IDLE, FSMState.ENTERING):
                state.fsm_state = FSMState.ENTERING
                state.zone_id = zone_id
                state.zone_name = zone.get("name", "")
                if state.first_entry_time is None:
                    state.first_entry_time = now

            elif state.fsm_state == FSMState.ENTERING:
                state.fsm_state = FSMState.PRESENT

            if state.first_entry_time:
                dwell = now - state.first_entry_time
                if dwell >= dwell_threshold and state.fsm_state not in (FSMState.LOITERING, FSMState.THREAT):
                    state.fsm_state = FSMState.LOITERING

                if dwell >= dwell_threshold * 2:
                    # Two-tiered confidence gate: θ_alert required for THREAT
                    if det.get("confidence", 0) > THETA_ALERT:
                        # Transition to THREAT on first crossing
                        if state.fsm_state == FSMState.LOITERING:
                            state.fsm_state = FSMState.THREAT
                        # CRITICAL: call _accumulate_and_fire on EVERY frame in
                        # THREAT state — not just on state transition.
                        # This retries face recognition each frame until a clean
                        # crop is captured, and keeps the severity integral S(id,t)
                        # compounding continuously as the patent specifies.
                        if state.fsm_state == FSMState.THREAT:
                            self._accumulate_and_fire(
                                state, det, zone, zone_id, "LOITERING", frame, now
                            )
                            return True

            return True  # inside zone = violation for scheduler
        else:
            # Object is outside the zone.
            if state.fsm_state != FSMState.IDLE:
                if state.zone_exit_time is None:
                    # First frame outside zone — start hysteresis timer, do NOT reset yet
                    state.zone_exit_time = now
                    logger.debug(
                        f"[HYSTERESIS] Track {state.track_id} exited zone, "
                        f"grace period {self.HYSTERESIS_SECONDS}s started"
                    )
                elif now - state.zone_exit_time >= self.HYSTERESIS_SECONDS:
                    # Grace period expired — genuine zone exit, reset FSM and severity
                    logger.debug(
                        f"[HYSTERESIS] Track {state.track_id} confirmed exit after "
                        f"{now - state.zone_exit_time:.1f}s — resetting FSM"
                    )
                    state.fsm_state = FSMState.IDLE
                    state.first_entry_time = None
                    state.face_checked = False
                    state.last_face_check_time = 0.0
                    state.severity_sum = 0.0
                    state.embedding_buffer.clear()
                    state.face_check_count = 0
                    state.zone_exit_time = None
                    state.peak_risk_score = 0.0
                # else: within hysteresis window — preserve FSM state and severity_sum
            return False
        # Object is inside zone — clear any pending exit timer
        state.zone_exit_time = None

    def _eval_tripwire(self, state, det, zone, zone_id, pixel_pts, config,
                       center, frame, now) -> bool:
        if state.prev_center is None:
            return False
        direction = detect_line_crossing(
            state.prev_center, center, pixel_pts[0], pixel_pts[1]
        )
        if direction is None:
            return False
        required_dir = config.get("direction", "any")
        if required_dir != "any" and direction != required_dir:
            return False
        if det.get("confidence", 0) > THETA_ALERT:
            state.fsm_state = FSMState.THREAT
            state.zone_id = zone_id
            state.zone_name = zone.get("name", "")
            self._accumulate_and_fire(state, det, zone, zone_id, "TRIPWIRE_CROSS", frame, now)
            return True
        return False

    def _eval_speedgate(self, state, det, zone, zone_id, pixel_pts, config,
                        center, frame, now) -> bool:
        if state.prev_center is None:
            return False
        direction = detect_line_crossing(
            state.prev_center, center, pixel_pts[0], pixel_pts[1]
        )
        if direction is None:
            return False
        pixels_per_metre = config.get("pixels_per_metre", 100.0)
        speed_limit = config.get("speed_limit", 5.0)
        pixel_dist = pixel_distance(state.prev_center, center)
        speed_mps = (pixel_dist / max(pixels_per_metre, 1.0)) / 0.033
        if speed_mps > speed_limit:
            if det.get("confidence", 0) > THETA_ALERT:
                state.fsm_state = FSMState.THREAT
                state.zone_id = zone_id
                state.zone_name = zone.get("name", "")
                self._accumulate_and_fire(state, det, zone, zone_id, "SPEED_GATE", frame, now)
                return True
        return False

    # ── V2 Risk Engine ────────────────────────────────────────────────────────
    def _accumulate_and_fire(self, state, det, zone, zone_id, violation_type, frame, now):
        """
        Patent §E + §F:
        1. Run biometric check to determine A(id) (authorization tensor).
           Only set face_checked=True when a VALID embedding was successfully
           extracted. If the face crop fails or dlib returns None, keep retrying
           on subsequent frames so a briefly-turned face doesn't permanently
           lock the identity as UNKNOWN.
        2. Accumulate severity integral: S += C_i · (1−A(id)) · e^(γ·(t−t_i))
        3. Compute logistic risk: R = 1 / (1 + e^(−k·(S−0.5)))
        4. If R ≥ R_threshold → dispatch event.
        """
        # ── Step 1: Multi-frame biometric check → A(id) ──────────────────────
        # Strategy: collect up to 3 embeddings (one per 2s interval) then match
        # the AVERAGED embedding. Averaging cancels blur/pose noise in individual
        # frames, dramatically improving recognition at 2m+ or in low light.
        MAX_EMBED_SAMPLES = 3
        if not state.face_checked and face_utils.is_available() and self._enrolled_faces:
            if now - state.last_face_check_time > 2.0:
                state.last_face_check_time = now
                bbox = det["bbox"]
                x1, y1, x2, y2 = [int(v) for v in bbox]
                h, w = frame.shape[:2]
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(w, x2), min(h, y2)
                face_crop = frame[y1:y2, x1:x2]
                if face_crop.size > 0:
                    emb = face_utils.extract_embedding(face_crop)
                    if emb is not None:
                        state.embedding_buffer.append(emb)
                        state.face_check_count += 1
                        logger.debug(
                            f"[FACE] Track {state.track_id}: "
                            f"sample {state.face_check_count}/{MAX_EMBED_SAMPLES} collected"
                        )

                    # Match once we have enough samples
                    if len(state.embedding_buffer) >= MAX_EMBED_SAMPLES:
                        # Average all collected embeddings — much more stable than single-frame
                        avg_emb = np.mean(state.embedding_buffer, axis=0).astype(np.float32)
                        # L2-normalise (ArcFace expects unit vectors for cosine similarity)
                        norm = np.linalg.norm(avg_emb)
                        if norm > 1e-6:
                            avg_emb /= norm
                        name, sim = face_utils.match_face(
                            avg_emb, self._enrolled_faces, FACE_MATCH_THRESHOLD
                        )
                        logger.info(
                            f"[FACE] Track {state.track_id}: "
                            f"avg of {len(state.embedding_buffer)} embeddings → "
                            f"'{name or 'UNKNOWN'}' (sim={sim:.3f})"
                        )
                        if name:
                            state.identity = name
                            state.auth_score = sim
                            state.A_id = 1.0
                            state.severity_sum = 0.0
                            state.face_checked = True  # confirmed, stop collecting
                        else:
                            state.identity = "UNKNOWN"
                            state.auth_score = 0.0
                            state.A_id = 0.0
                            # Rolling window: drop oldest, keep collecting
                            state.embedding_buffer.pop(0)


        # ── Step 2: Accumulate S(id,t) = Σ C_i·(1−A_id)·e^(−γ·(t−t_i)) ───────────
        # CORRECT sign: negative exponent so older observations decay (matter less).
        # Positive exponent caused S to explode → instant CRITICAL on any time gap.
        C_i = det.get("confidence", 0.0)
        t_i = state.last_observation_time
        dt  = max(0.0, now - t_i)
        contribution = C_i * (1.0 - state.A_id) * math.exp(-RISK_GAMMA * dt)
        state.severity_sum += contribution

        # ── Step 3: Logistic transformation R(id,t) ─────────────────────────────
        S = state.severity_sum
        R = 1.0 / (1.0 + math.exp(-RISK_K * (S - 0.5)))
        R = round(min(1.0, max(0.0, R)), 3)
        level = score_to_level(R)

        # Update peak_risk_score: fed back to scheduler as continuous V(c,t)
        # This is what enables proportional urgency modulation (patent §B extension)
        state.peak_risk_score = R


        # ── Step 4: Dispatch if R ≥ R_threshold OR user is VERIFIED (Access Log) ────
        if R < RISK_THRESHOLD and state.identity == "UNKNOWN":
            logger.debug(f"Risk R={R:.3f} below threshold {RISK_THRESHOLD} — suppressed")
            return

        # Per-track cooldown: severity integral keeps compounding (patent-correct)
        # but only fire a DB event + alert once per EVENT_COOLDOWN_S seconds.
        if now - state.last_event_time < self.EVENT_COOLDOWN_S:
            return
        state.last_event_time = now

        event = ViolationEvent(
            camera_id=state.camera_id,
            zone_id=zone_id,
            zone_name=state.zone_name or zone.get("name", ""),
            track_id=state.track_id,
            object_class=det["class_name"],
            confidence=C_i,
            risk_score=R,
            risk_level=level,
            identity=state.identity,
            auth_score=state.auth_score,
            violation_type=violation_type,
            frame=frame.copy(),
            bbox=det["bbox"],
        )
        for cb in self._violation_callbacks:
            try:
                cb(event)
            except Exception as e:
                logger.error(f"Decision callback error: {e}")


# ── Global singleton ──────────────────────────────────────────────────────────
decision_agent = DecisionAgent()
