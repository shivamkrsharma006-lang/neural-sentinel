import asyncio
import json
import time
import cv2
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException
from fastapi.responses import StreamingResponse, Response
from sqlalchemy.orm import Session
from database import get_db, Camera, User
from auth import get_current_user, decode_token
from agents.detection_agent import detection_agent, get_camera_name
from agents.decision_agent import decision_agent
from agents.response_agent import ws_clients, ws_lock

router = APIRouter(tags=["stream"])


# ── MJPEG stream with zone + detection overlay ─────────────────────────────────
ZONE_COLORS = {
    "polygon":   (0, 200, 255),   # Orange
    "tripwire":  (255, 50,  50),  # Blue
    "speedgate": (50,  255, 50),  # Green
}

STATE_COLORS = {
    "IDLE":      (180, 180, 180),
    "ENTERING":  (0,   200, 255),
    "PRESENT":   (0,   255, 200),
    "LOITERING": (0,   165, 255),
    "THREAT":    (0,   0,   255),
}


def _draw_overlay(frame: np.ndarray, camera_id: int) -> np.ndarray:
    """Draw zone polygons, detection boxes, and FSM state labels on frame."""
    h, w = frame.shape[:2]

    # ── Zones ──────────────────────────────────────────────────────────────────
    zones = decision_agent._zones.get(camera_id, [])
    for zone in zones:
        if not zone.get("active", True):
            continue
        zone_type = zone["zone_type"]
        color = ZONE_COLORS.get(zone_type, (255, 255, 0))
        try:
            pts_raw = json.loads(zone["points_json"])
            pts = [(int(p["x"] * w), int(p["y"] * h)) for p in pts_raw]
        except Exception:
            continue

        if zone_type == "polygon" and len(pts) >= 3:
            overlay = frame.copy()
            cv2.fillPoly(overlay, [np.array(pts)], tuple(int(c) for c in color))
            cv2.addWeighted(overlay, 0.15, frame, 0.85, 0, frame)
            cv2.polylines(frame, [np.array(pts)], True, color, 2)
        elif zone_type in ("tripwire", "speedgate") and len(pts) >= 2:
            cv2.line(frame, pts[0], pts[1], color, 2)
            if zone_type == "tripwire":
                mx = (pts[0][0] + pts[1][0]) // 2
                my = (pts[0][1] + pts[1][1]) // 2
                cv2.arrowedLine(frame, (mx, my), (mx + 20, my), color, 2)

        if pts:
            cv2.putText(frame, zone["name"], pts[0],
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)

    # ── Detection boxes ────────────────────────────────────────────────────────
    result = detection_agent.get_result(camera_id)
    if result and result.detections:
        for det in result.detections:
            x1, y1, x2, y2 = [int(v) for v in det["bbox"]]
            conf   = det["confidence"]
            cls    = det["class_name"]
            tid    = det["track_id"]
            key    = (camera_id, tid)
            state_obj  = decision_agent._states.get(key)
            state_name = state_obj.fsm_state.value if state_obj else "IDLE"
            color  = STATE_COLORS.get(state_name, (180, 180, 180))
            identity = state_obj.identity if state_obj else "UNKNOWN"
            
            if identity != "UNKNOWN":
                color = (0, 255, 0)  # Verified green
                label = f"#{tid} {identity} {conf:.0%} [VERIFIED]"
            else:
                label = f"#{tid} {identity} {conf:.0%} [{state_name}]"

            # Clamp to frame bounds
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)

            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            lx, ly = x1, max(y1 - 6, 12)
            # Background for label
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.42, 1)
            cv2.rectangle(frame, (lx, ly - th - 2), (lx + tw, ly + 2), color, -1)
            cv2.putText(frame, label, (lx, ly),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 1, cv2.LINE_AA)

    # ── HUD label ──────────────────────────────────────────────────────────────
    cam_label = get_camera_name(camera_id)
    n_det = len(result.detections) if result and result.detections else 0
    hud = f"{cam_label}  |  {n_det} object{'s' if n_det != 1 else ''}  |  Neural Sentinel"
    cv2.rectangle(frame, (0, 0), (w, 26), (0, 0, 0), -1)
    cv2.putText(frame, hud, (8, 18),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return frame


def _make_disarmed_frame() -> bytes:
    """Return a black JPEG frame with 'System Disarmed' text."""
    placeholder = np.zeros((360, 640, 3), dtype=np.uint8)
    cv2.putText(placeholder, "System Disarmed", (160, 170),
                cv2.FONT_HERSHEY_SIMPLEX, 1.2, (60, 60, 60), 2, cv2.LINE_AA)
    cv2.putText(placeholder, "Click 'Arm' to resume surveillance", (100, 210),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (50, 50, 50), 1, cv2.LINE_AA)
    _, buf = cv2.imencode(".jpg", placeholder, [cv2.IMWRITE_JPEG_QUALITY, 60])
    return buf.tobytes()


def _frame_generator(camera_id: int):
    """MJPEG frame generator — capped at 25fps with persistent overlay."""
    frame_interval = 1.0 / 25  # 25fps cap
    while True:
        t0 = time.time()

        # ── Disarmed: serve black placeholder, don't touch camera hardware ──
        if not detection_agent._armed:
            jpg = _make_disarmed_frame()
            yield (
                b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                + jpg
                + b"\r\n"
            )
            time.sleep(1.0)   # 1fps when idle — zero CPU waste
            continue

        frame = detection_agent.get_snapshot(camera_id)
        if frame is None:
            placeholder = np.zeros((360, 640, 3), dtype=np.uint8)
            cv2.putText(placeholder, "Connecting...", (220, 180),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (80, 80, 80), 2)
            frame = placeholder
        else:
            frame = _draw_overlay(frame, camera_id)

        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        yield (
            b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
            + buf.tobytes()
            + b"\r\n"
        )
        # Sleep remaining time to maintain target fps
        elapsed = time.time() - t0
        sleep_t = max(0.0, frame_interval - elapsed)
        if sleep_t > 0:
            time.sleep(sleep_t)


@router.get("/stream/{camera_id}")
def video_stream(camera_id: int):
    """MJPEG stream — no auth required so <img> tags work directly."""
    return StreamingResponse(
        _frame_generator(camera_id),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.get("/snapshot/{camera_id}")
def snapshot(camera_id: int):
    """Single JPEG snapshot for zone editor canvas."""
    frame = detection_agent.get_snapshot(camera_id)
    if frame is None:
        raise HTTPException(404, "No frame available")
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return Response(content=buf.tobytes(), media_type="image/jpeg")


# ── WebSocket for real-time events ────────────────────────────────────────────
@router.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    """
    Long-lived WebSocket for real-time event push.

    Token is validated ONCE at connection time. We extract the `sub` claim
    rather than re-checking expiry on every ping — the session lives until
    the client disconnects, not until the JWT's exp timestamp.
    """
    import logging
    ws_logger = logging.getLogger("ws.events")

    token = websocket.query_params.get("token", "")
    from jose import jwt as _jwt, JWTError
    from config import SECRET_KEY, ALGORITHM

    # Accept tokens that are expired but otherwise structurally valid
    # (correct signature, correct user). This prevents reconnect-storms
    # caused by a token expiring while the WS is already open.
    try:
        payload = _jwt.decode(
            token, SECRET_KEY, algorithms=[ALGORITHM],
            options={"verify_exp": False}   # ignore expiry on persistent WS
        )
    except JWTError:
        await websocket.close(code=4001)
        return

    user_id = payload.get("sub")
    if not user_id:
        await websocket.close(code=4001)
        return

    await websocket.accept()
    with ws_lock:
        ws_clients.add(websocket)
    ws_logger.info(f"WebSocket client connected (user_id={user_id})")

    try:
        while True:
            # Wait for a client message OR timeout after 25s for a server ping.
            # receive_text raises WebSocketDisconnect when the client closes.
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=25.0)
                # Client can send {"type": "pong"} or any heartbeat — just ignore it
            except asyncio.TimeoutError:
                # 25s idle — send a keepalive ping
                try:
                    await websocket.send_text(json.dumps({"type": "ping"}))
                except Exception:
                    break   # send failed — client is gone
    except WebSocketDisconnect:
        ws_logger.info(f"WebSocket client disconnected (user_id={user_id})")
    except Exception as e:
        ws_logger.debug(f"WebSocket closed unexpectedly: {e}")
    finally:
        with ws_lock:
            ws_clients.discard(websocket)