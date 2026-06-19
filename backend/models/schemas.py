from pydantic import BaseModel, field_validator, model_validator
from typing import Optional
from datetime import datetime, timezone


# ── Auth ──────────────────────────────────────────────────────────────────────
class UserCreate(BaseModel):
    username: str
    email: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class UserOut(BaseModel):
    id: int
    username: str
    email: str
    created_at: datetime
    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ── Camera ────────────────────────────────────────────────────────────────────
class CameraCreate(BaseModel):
    name: str
    source: str

class CameraUpdate(BaseModel):
    name: Optional[str] = None
    source: Optional[str] = None

class CameraOut(BaseModel):
    id: int
    name: str
    source: str
    status: str
    created_at: datetime
    class Config:
        from_attributes = True


# ── Zone ──────────────────────────────────────────────────────────────────────
class ZoneCreate(BaseModel):
    name: str
    zone_type: str
    points_json: str
    config_json: str = "{}"

class ZoneOut(BaseModel):
    id: int
    camera_id: int
    name: str
    zone_type: str
    points_json: str
    config_json: str
    active: bool
    created_at: datetime
    class Config:
        from_attributes = True


# ── Event ─────────────────────────────────────────────────────────────────────
class EventOut(BaseModel):
    id: int
    camera_id: int
    camera_name: Optional[str] = None
    zone_id: Optional[int] = None
    zone_name: Optional[str] = None
    event_type: str
    risk_score: float
    risk_level: str
    identity: str
    object_class: str
    confidence: float
    frame_path: Optional[str] = None
    timestamp: str  # UTC ISO string with Z suffix — JS parses correctly as UTC

    @classmethod
    def model_validate(cls, obj, **kwargs):
        """Override to inject camera_name and correct UTC timestamp."""
        data = {
            'id': obj.id,
            'camera_id': obj.camera_id,
            'camera_name': obj.camera.name if hasattr(obj, 'camera') and obj.camera else f'Camera {obj.camera_id}',
            'zone_id': obj.zone_id,
            'zone_name': obj.zone.name if hasattr(obj, 'zone') and obj.zone else None,
            'event_type': obj.event_type,
            'risk_score': obj.risk_score,
            'risk_level': obj.risk_level,
            'identity': obj.identity,
            'object_class': obj.object_class,
            'confidence': obj.confidence,
            'frame_path': obj.frame_path,
            # Always append Z so JavaScript Date() knows it's UTC
            'timestamp': (obj.timestamp.strftime('%Y-%m-%dT%H:%M:%S') + 'Z')
                         if isinstance(obj.timestamp, datetime) else str(obj.timestamp) + 'Z',
        }
        return cls(**data)

    class Config:
        from_attributes = True


# ── Face ──────────────────────────────────────────────────────────────────────
class FaceOut(BaseModel):
    id: int
    name: str
    created_at: datetime
    class Config:
        from_attributes = True


# ── Alert Config ──────────────────────────────────────────────────────────────
class AlertConfigCreate(BaseModel):
    alert_type: str
    config_json: str
    active: bool = True

class AlertConfigOut(BaseModel):
    id: int
    alert_type: str
    config_json: str
    active: bool
    class Config:
        from_attributes = True
