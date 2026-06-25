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
from utils.color_utils import extract_dominant_colors, get_clothing_colors
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
    # ── V4 Metadata Pipeline fields ──────────────────────────────────────────
    direction: str = ""
    speed_estimate: str = ""
    duration_seconds: float = 0.0
    fsm_state: str = ""
    dominant_colors: List[str] = field(default_factory=list)
    object_details: str = "{}"


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

    # How long a verified identity stays in the camera-level cache (seconds)
    VERIFIED_CACHE_TTL = 300.0  # 5 minutes

    def __init__(self):
        self._zones: Dict[int, List[dict]] = {}
        self._states: Dict[Tuple[int, int], ObjectState] = {}
        self._enrolled_faces: List[Tuple[str, np.ndarray]] = []
        self._violation_callbacks = []
        self._frame_dims: Dict[int, Tuple[int, int]] = {}
        # ── Verified Identity Cache ────────────────────────────────────────────
        # Remembers recently verified people per camera so that when ByteTrack
        # reassigns a new track_id to the same person, we can instantly
        # re-identify them from their embedding without waiting for dwell→THREAT.
        # Structure: {camera_id: [(name, embedding, last_seen_time)]}
        self._verified_cache: Dict[int, List[Tuple[str, np.ndarray, float]]] = {}

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
            state.zone_exit_time = None
            if state.fsm_state == FSMState.IDLE:
                state.fsm_state = FSMState.ENTERING
                state.zone_id = zone_id
                state.zone_name = zone.get("name", "")
                if state.first_entry_time is None:
                    state.first_entry_time = now

            elif state.fsm_state == FSMState.ENTERING:
                state.fsm_state = FSMState.PRESENT
                state.zone_id = zone_id
                state.zone_name = zone.get("name", "")

            # Run biometric check on every frame inside the zone if not verified yet
            verified_name = self._check_biometrics_if_needed(state, det, frame, now)
            if verified_name:
                # If verified, trigger event immediately to record verified access, bypassing cooldown
                self._accumulate_and_fire(
                    state, det, zone, zone_id, "VERIFIED_ACCESS", frame, now, bypass_cooldown=True
                )

            if state.first_entry_time:
                dwell = now - state.first_entry_time
                
                # Only escalate or run loitering/threat logic for UNKNOWN tracks
                if state.identity == "UNKNOWN":
                    if dwell >= dwell_threshold and state.fsm_state not in (FSMState.LOITERING, FSMState.THREAT):
                        state.fsm_state = FSMState.LOITERING

                    # If already in THREAT state, keep compounding severity and checking face
                    if state.fsm_state == FSMState.THREAT:
                        self._accumulate_and_fire(
                            state, det, zone, zone_id, "LOITERING", frame, now
                        )
                        return True

                    # Transition to THREAT if dwell meets threshold and confidence is high
                    elif dwell >= dwell_threshold * 2:
                        if det.get("confidence", 0) > THETA_ALERT:
                            state.fsm_state = FSMState.THREAT
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
            # Check biometrics first
            verified_name = self._check_biometrics_if_needed(state, det, frame, now)
            if state.identity == "UNKNOWN":
                state.fsm_state = FSMState.THREAT
                state.zone_id = zone_id
                state.zone_name = zone.get("name", "")
                self._accumulate_and_fire(
                    state, det, zone, zone_id, "TRIPWIRE_CROSS", frame, now
                )
            else:
                state.fsm_state = FSMState.PRESENT
                state.zone_id = zone_id
                state.zone_name = zone.get("name", "")
                self._accumulate_and_fire(
                    state, det, zone, zone_id, "TRIPWIRE_CROSS", frame, now, bypass_cooldown=True
                )
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
                verified_name = self._check_biometrics_if_needed(state, det, frame, now)
                if state.identity == "UNKNOWN":
                    state.fsm_state = FSMState.THREAT
                    state.zone_id = zone_id
                    state.zone_name = zone.get("name", "")
                    self._accumulate_and_fire(
                        state, det, zone, zone_id, "SPEED_GATE", frame, now
                    )
                else:
                    state.fsm_state = FSMState.PRESENT
                    state.zone_id = zone_id
                    state.zone_name = zone.get("name", "")
                    self._accumulate_and_fire(
                        state, det, zone, zone_id, "SPEED_GATE", frame, now, bypass_cooldown=True
                    )
                return True
        return False

    def _verify_track(self, state, name: str, sim: float):
        """Apply verification to a track: set identity, lock face checks, de-escalate."""
        state.identity = name
        state.auth_score = sim
        state.A_id = 1.0
        state.severity_sum = 0.0
        state.face_checked = True  # Verification lock for this track
        state.peak_risk_score = 0.0
        # Only de-escalate if currently in a threat/loitering state
        if state.fsm_state in (FSMState.THREAT, FSMState.LOITERING):
            state.fsm_state = FSMState.PRESENT
        state.embedding_buffer.clear()
        logger.info(f"[FACE] ✓ Track {state.track_id} verified as '{name}' (sim={sim:.3f})")
        # Store in camera-level cache for fast re-identification on track changes
        self._cache_verified_identity(state.camera_id, name, state.embedding_buffer, sim)
        self._retroactive_log_correction(state.camera_id, state.track_id, name)

    def _cache_verified_identity(self, camera_id: int, name: str, embedding_buffer: list, sim: float):
        """Cache a verified identity at the camera level for fast re-ID on track changes."""
        # We need to store the last known good embedding. Use the enrolled face embedding.
        for enrolled_name, enrolled_emb in self._enrolled_faces:
            if enrolled_name == name:
                cache = self._verified_cache.setdefault(camera_id, [])
                # Replace existing entry for same name, or add new
                cache[:] = [(n, e, t) for n, e, t in cache if n != name]
                cache.append((name, enrolled_emb.copy(), time.time()))
                logger.info(f"[CACHE] Stored verified identity '{name}' in camera {camera_id} cache")
                return

    def _check_verified_cache(self, camera_id: int, embedding: np.ndarray, now: float) -> Optional[Tuple[str, float]]:
        """Check if an embedding matches a recently verified person on this camera."""
        cache = self._verified_cache.get(camera_id, [])
        if not cache:
            return None
        # Purge expired entries
        cache[:] = [(n, e, t) for n, e, t in cache if now - t < self.VERIFIED_CACHE_TTL]
        if not cache:
            return None
        # Match against cache
        for name, cached_emb, _ in cache:
            sim = float(np.dot(embedding, cached_emb))
            if sim >= FACE_MATCH_THRESHOLD:
                logger.info(f"[CACHE] Fast re-ID hit: '{name}' (sim={sim:.3f})")
                return name, sim
        return None

    def _check_biometrics_if_needed(self, state, det, frame, now) -> Optional[str]:
        """
        Hybrid biometric check — runs for ANY unverified track (face_checked=False):

        Layer 0 — Verified Cache:  Check the embedding against recently verified
                  people on this camera. This handles ByteTrack reassigning a new
                  track_id to someone who was JUST verified 2 seconds ago.
        Layer 1 — Single-frame:   Direct enrolled-face matching.
        Layer 2 — Rolling avg:    3-frame averaged embedding matching.

        Returns the verified identity name if successful, else None.
        CRITICAL: For UNKNOWN tracks, face_checked is NEVER set to True by
        a failed check. It stays False so checks continue every 0.5s forever.
        """
        if state.face_checked:
            return None  # Already verified — skip
        if not face_utils.is_available() or not self._enrolled_faces:
            return None
        # ── Adaptive Backoff Throttle (Patent §F extension) ─────────────────
        # Aggressive checks initially (0.5s), then back off to save CPU:
        #   0–120s  → every 0.5s  (aggressive — person just appeared)
        #   120–300s → every 2.0s  (moderate — likely genuinely unknown)
        #   300s+    → every 5.0s  (relaxed — still checking, just less often)
        tracking_duration = now - state.first_entry_time if state.first_entry_time else 0.0
        if tracking_duration < 120.0:
            check_interval = 0.5
        elif tracking_duration < 300.0:
            check_interval = 2.0
        else:
            check_interval = 5.0
        if now - state.last_face_check_time < check_interval:
            return None
        state.last_face_check_time = now
        state.face_check_count += 1

        bbox = det["bbox"]
        x1, y1, x2, y2 = [int(v) for v in bbox]
        h, w = frame.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        face_crop = frame[y1:y2, x1:x2]
        if face_crop.size == 0:
            return None

        emb = face_utils.extract_embedding(face_crop)
        if emb is None:
            return None

        # ── Layer 0: Verified cache (instant, ~0.01ms) ──────────────────────
        cache_hit = self._check_verified_cache(state.camera_id, emb, now)
        if cache_hit:
            name, sim = cache_hit
            self._verify_track(state, name, sim)
            return name

        # ── Layer 1: Single-frame enrolled match ────────────────────────────
        name, sim = face_utils.match_face(
            emb, self._enrolled_faces, FACE_MATCH_THRESHOLD
        )
        logger.info(
            f"[FACE] Track {state.track_id}: single-frame → "
            f"'{name or 'UNKNOWN'}' (sim={sim:.3f})"
        )
        if name:
            self._verify_track(state, name, sim)
            return name

        # ── Layer 2: Rolling multi-frame average ────────────────────────────
        state.embedding_buffer.append(emb)
        if len(state.embedding_buffer) > 3:
            state.embedding_buffer.pop(0)

        if len(state.embedding_buffer) >= 2:
            avg_emb = np.mean(state.embedding_buffer, axis=0)
            norm = np.linalg.norm(avg_emb)
            if norm > 1e-6:
                avg_emb /= norm
            name, sim = face_utils.match_face(
                avg_emb, self._enrolled_faces, FACE_MATCH_THRESHOLD
            )
            logger.info(
                f"[FACE] Track {state.track_id}: averaged ({len(state.embedding_buffer)} frames) → "
                f"'{name or 'UNKNOWN'}' (sim={sim:.3f})"
            )
            if name:
                self._verify_track(state, name, sim)
                return name

        # Still UNKNOWN — do NOT lock face_checked, keep trying on next frames
        state.identity = "UNKNOWN"
        state.auth_score = 0.0
        state.A_id = 0.0
        return None

    # ── V2 Risk Engine ────────────────────────────────────────────────────────
    def _accumulate_and_fire(self, state, det, zone, zone_id, violation_type, frame, now, bypass_cooldown=False):
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
        # ── Step 1: Instant biometric check & Verification Lock ─────────────────
        self._check_biometrics_if_needed(state, det, frame, now)

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

        # Per-track cooldown: bypass if requested (e.g. for instant verification logging)
        if not bypass_cooldown:
            if now - state.last_event_time < self.EVENT_COOLDOWN_S:
                return
        state.last_event_time = now

        # ── V4 Metadata: direction estimation ───────────────────────────────
        direction = ""
        speed_est = "stationary"
        if state.prev_center:
            current_center = tuple(det["center"])
            dx = current_center[0] - state.prev_center[0]
            dy = current_center[1] - state.prev_center[1]
            dist = math.sqrt(dx * dx + dy * dy)
            if dist < 3:
                direction = "stationary"
                speed_est = "stationary"
            else:
                if dist < 15:
                    speed_est = "slow"
                elif dist < 40:
                    speed_est = "normal"
                else:
                    speed_est = "fast"
                # Determine primary direction
                if abs(dy) > abs(dx):
                    direction = "entering" if dy > 0 else "exiting"
                else:
                    direction = "crossing"

        # ── V4 Metadata: duration ──────────────────────────────────────
        duration = now - state.first_entry_time if state.first_entry_time else 0.0

        # ── V4 Metadata: dominant colors (lightweight, runs on existing crop) ──
        colors = []
        obj_details = {}
        try:
            colors = extract_dominant_colors(frame, det["bbox"], n_colors=2)
            if det["class_name"] == "person":
                clothing = get_clothing_colors(frame, det["bbox"])
                obj_details = {
                    "clothing_upper": clothing.get("upper", []),
                    "clothing_lower": clothing.get("lower", []),
                    "face_detected": state.face_checked,
                    "match_confidence": round(state.auth_score, 3),
                }
            else:
                plate_text = ""
                if det["class_name"] in ("car", "truck", "motorcycle", "bus"):
                    bbox = det["bbox"]
                    x1, y1, x2, y2 = [int(v) for v in bbox]
                    h, w = frame.shape[:2]
                    x1, y1 = max(0, x1), max(0, y1)
                    x2, y2 = min(w, x2), min(h, y2)
                    vehicle_crop = frame[y1:y2, x1:x2]
                    if vehicle_crop.size > 0:
                        from utils import lpr_utils
                        plate_text = lpr_utils.read_license_plate(vehicle_crop) or ""
                
                obj_details = {
                    "vehicle_type": det["class_name"],
                    "color": colors[0] if colors else "",
                    "license_plate": plate_text,
                }
        except Exception as e:
            logger.debug(f"Color/LPR extraction failed: {e}")

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
            direction=direction,
            speed_estimate=speed_est,
            duration_seconds=round(duration, 1),
            fsm_state=state.fsm_state.value,
            dominant_colors=colors,
            object_details=json.dumps(obj_details),
        )
        for cb in self._violation_callbacks:
            try:
                cb(event)
            except Exception as e:
                logger.error(f"Decision callback error: {e}")

    def _retroactive_log_correction(self, camera_id: int, track_id: int, identity: str):
        """
        Retroactively updates historical events for the same track within the database.
        Sets identity to verified name, and resolves risk score/level to low.
        """
        def _update():
            from database import SessionLocal, Event
            from datetime import datetime, timedelta
            db = SessionLocal()
            try:
                # Find all events in the last 15 minutes for this track/camera that are UNKNOWN
                cutoff = datetime.utcnow() - timedelta(minutes=15)
                events = db.query(Event).filter(
                    Event.camera_id == camera_id,
                    Event.track_id == track_id,
                    Event.identity == "UNKNOWN",
                    Event.timestamp >= cutoff
                ).all()
                
                if events:
                    for e in events:
                        e.identity = identity
                        e.risk_score = 0.0
                        e.risk_level = "LOW"
                    db.commit()
                    logger.info(f"[LOG CORRECTION] Retroactively corrected {len(events)} events for track {track_id} -> '{identity}'")
            except Exception as e:
                logger.error(f"Error during log correction: {e}")
            finally:
                db.close()
                
        import threading
        threading.Thread(target=_update, daemon=True, name=f"log-correct-{track_id}").start()


# ── Global singleton ──────────────────────────────────────────────────────────
decision_agent = DecisionAgent()
