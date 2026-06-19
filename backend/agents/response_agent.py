"""
Response Agent — Evidence capture, structured logging, and multi-channel alert dispatch.

On each ViolationEvent:
  1. Store JPEG evidence frame IN MEMORY only (not disk) — cleared on restart
  2. Insert Event record into database
  3. Broadcast to all connected WebSocket clients
  4. Dispatch SMS/call (Twilio) and webhook alerts (Telegram/Discord/Slack)
     with per-contact cooldown throttle

Frames are available via /api/events/{id}/frame while backend is running.
Use /api/events/{id}/frame/save to download to disk on demand.
"""

import json
import time
import logging
import threading
import asyncio
import base64
import cv2
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Optional, Set
import httpx

from config import (
    FRAMES_DIR, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER,
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    DISCORD_WEBHOOK_URL, SLACK_WEBHOOK_URL,
    ALERT_COOLDOWN
)
from agents.decision_agent import ViolationEvent

logger = logging.getLogger(__name__)

# Global WebSocket connection set (populated by the stream router)
ws_clients: Set = set()
ws_lock = threading.Lock()
_loop: Optional[asyncio.AbstractEventLoop] = None


def set_event_loop(loop: asyncio.AbstractEventLoop):
    global _loop
    _loop = loop


# ── Alert cooldown tracker ─────────────────────────────────────────────────────
_last_alert: dict = {}   # key -> last_alert_timestamp
_cooldown_lock = threading.Lock()


def _can_alert(key: str) -> bool:
    with _cooldown_lock:
        last = _last_alert.get(key, 0)
        if time.time() - last >= ALERT_COOLDOWN:
            _last_alert[key] = time.time()
            return True
        return False


class ResponseAgent:

    def __init__(self):
        self._db_session_factory = None
        self._alert_configs_cache: list = []
        # Bounded pool — max 4 concurrent alert+DB threads to prevent explosion
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="response")

    def set_db_factory(self, factory):
        self._db_session_factory = factory

    def refresh_alert_configs(self, configs: list):
        self._alert_configs_cache = [c for c in configs if c.get("active")]

    # ── Main handler ────────────────────────────────────────────────────────
    def handle_violation(self, event: ViolationEvent):
        """Called by DecisionAgent for each new violation."""
        self._executor.submit(self._process, event)

    def _process(self, event: ViolationEvent):
        try:
            frame_path = self._save_frame(event)
            event_record = self._save_event(event, frame_path)
            self._broadcast_ws(event, frame_path)
            self._dispatch_alerts(event, frame_path)
        except Exception as e:
            logger.error(f"ResponseAgent error: {e}", exc_info=True)

    # ── Frame capture (memory + disk) ──────────────────────────────────────
    def _save_frame(self, event: ViolationEvent) -> str:
        """Encode evidence frame as JPEG, store in memory AND write to disk.
        Disk persistence means frames survive server restarts — fixing
        the 'Frame expired' error seen when viewing old events."""
        from agents.detection_agent import store_evidence_frame
        frame = event.frame.copy()
        x1, y1, x2, y2 = [int(v) for v in event.bbox]
        color = (0, 0, 255) if event.identity == "UNKNOWN" else (0, 200, 0)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        label = f"{event.identity} | R={event.risk_score:.2f} | {event.violation_type}"
        cv2.putText(frame, label, (x1, max(y1 - 8, 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        jpeg_bytes = buf.tobytes()
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
        key = f"cam{event.camera_id}_{event.violation_type}_{ts}"
        # store_evidence_frame writes to both in-memory dict AND disk
        store_evidence_frame(key, jpeg_bytes)
        return key


    # ── DB logging ───────────────────────────────────────────────────────────
    def _save_event(self, event: ViolationEvent, frame_path: str):
        if not self._db_session_factory:
            return None
        db = self._db_session_factory()
        try:
            from database import Event as DBEvent
            record = DBEvent(
                camera_id=event.camera_id,
                zone_id=event.zone_id,
                event_type=event.violation_type,
                risk_score=event.risk_score,
                risk_level=event.risk_level,
                identity=event.identity,
                object_class=event.object_class,
                confidence=event.confidence,
                frame_path=frame_path,
                timestamp=datetime.utcnow(),
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return record
        except Exception as e:
            logger.error(f"DB save error: {e}")
            db.rollback()
            return None
        finally:
            db.close()

    # ── WebSocket broadcast ──────────────────────────────────────────────────
    def _broadcast_ws(self, event: ViolationEvent, frame_path: str):
        from agents.detection_agent import get_camera_name
        message = json.dumps({
            "type": "violation",
            "camera_id": event.camera_id,
            "camera_name": get_camera_name(event.camera_id),
            "zone_name": event.zone_name,
            "violation_type": event.violation_type,
            "risk_score": event.risk_score,
            "risk_level": event.risk_level,
            "identity": event.identity,
            "object_class": event.object_class,
            "confidence": round(event.confidence, 3),
            # Always append Z so JS Date() knows it is UTC → correct local display
            "timestamp": datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        })
        if _loop and not _loop.is_closed():
            asyncio.run_coroutine_threadsafe(_async_broadcast(message), _loop)

    # ── Alert dispatch ───────────────────────────────────────────────────────
    def _dispatch_alerts(self, event: ViolationEvent, frame_path: str):
        if event.risk_level == "LOW":
            return  # Skip low-risk alerts
        alert_key = f"cam{event.camera_id}_{event.zone_id}"
        if not _can_alert(alert_key):
            return

        msg = (
            f"🚨 Neural Sentinel Alert\n"
            f"Camera: {event.camera_id} | Zone: {event.zone_name}\n"
            f"Type: {event.violation_type}\n"
            f"Object: {event.object_class} ({event.confidence:.0%})\n"
            f"Identity: {event.identity}\n"
            f"Risk: {event.risk_score:.2f} ({event.risk_level})\n"
            f"Time: {datetime.utcnow().strftime('%H:%M:%S UTC')}"
        )

        for cfg in self._alert_configs_cache:
            alert_type = cfg.get("alert_type", "")
            config = json.loads(cfg.get("config_json", "{}"))
            try:
                if alert_type == "sms":
                    self._send_sms(config.get("to_number", ""), msg)
                elif alert_type == "call":
                    self._send_call(config.get("to_number", ""))
                elif alert_type == "telegram":
                    self._send_telegram(
                        config.get("bot_token", TELEGRAM_BOT_TOKEN),
                        config.get("chat_id", TELEGRAM_CHAT_ID),
                        msg, frame_path
                    )
                elif alert_type == "discord":
                    self._send_discord(config.get("webhook_url", DISCORD_WEBHOOK_URL), msg, frame_path)
                elif alert_type == "slack":
                    self._send_slack(config.get("webhook_url", SLACK_WEBHOOK_URL), msg)
            except Exception as e:
                logger.error(f"Alert dispatch ({alert_type}) error: {e}")

    def _send_sms(self, to: str, msg: str):
        if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, to]):
            return
        from twilio.rest import Client
        Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN).messages.create(
            body=msg, from_=TWILIO_FROM_NUMBER, to=to
        )
        logger.info(f"SMS sent to {to}")

    def _send_call(self, to: str):
        if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, to]):
            return
        from twilio.rest import Client
        twiml = '<Response><Say>Neural Sentinel Alert. Intrusion detected. Check your dashboard immediately.</Say></Response>'
        Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN).calls.create(
            twiml=twiml, from_=TWILIO_FROM_NUMBER, to=to
        )
        logger.info(f"Call placed to {to}")

    def _send_telegram(self, token: str, chat_id: str, msg: str, frame_key: str):
        if not token or not chat_id:
            return
        from agents.detection_agent import get_evidence_frame
        with httpx.Client(timeout=10) as client:
            client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data={"chat_id": chat_id, "text": msg}
            )
            jpeg = get_evidence_frame(frame_key) if frame_key else None
            if jpeg:
                client.post(
                    f"https://api.telegram.org/bot{token}/sendPhoto",
                    data={"chat_id": chat_id},
                    files={"photo": ("frame.jpg", jpeg, "image/jpeg")},
                )

    def _send_discord(self, url: str, msg: str, frame_key: str):
        if not url:
            return
        from agents.detection_agent import get_evidence_frame
        jpeg = get_evidence_frame(frame_key) if frame_key else None
        with httpx.Client(timeout=10) as client:
            if jpeg:
                client.post(url, data={"content": msg}, files={"file": ("frame.jpg", jpeg, "image/jpeg")})
            else:
                client.post(url, json={"content": msg})

    def _send_slack(self, url: str, msg: str):
        if not url:
            return
        with httpx.Client(timeout=10) as client:
            client.post(url, json={"text": msg})


async def _async_broadcast(message: str):
    with ws_lock:
        clients = list(ws_clients)
    dead = []
    for ws in clients:
        try:
            await ws.send_text(message)
        except Exception:
            dead.append(ws)
    with ws_lock:
        for ws in dead:
            ws_clients.discard(ws)


# ── Global singleton ──────────────────────────────────────────────────────────
response_agent = ResponseAgent()
