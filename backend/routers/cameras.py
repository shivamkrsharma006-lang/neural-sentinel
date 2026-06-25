from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from database import get_db, Camera, User
from auth import get_current_user
from models.schemas import CameraCreate, CameraUpdate, CameraOut
from agents.detection_agent import detection_agent
import cv2

router = APIRouter(prefix="/cameras", tags=["cameras"])


def _sync_camera_to_agent(camera: Camera):
    detection_agent.add_camera(camera.id, camera.source, name=camera.name)


@router.get("", response_model=List[CameraOut])
def list_cameras(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    cameras = db.query(Camera).filter(Camera.user_id == current_user.id).all()
    result = []
    for cam in cameras:
        # Read live status from agent without mutating the ORM object
        cam_dict = {
            "id": cam.id,
            "name": cam.name,
            "source": cam.source,
            "status": detection_agent.get_camera_status(cam.id),
            "created_at": cam.created_at,
        }
        result.append(cam_dict)
    return result


@router.post("", response_model=CameraOut)
def add_camera(
    payload: CameraCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    cam = Camera(user_id=current_user.id, name=payload.name, source=payload.source)
    db.add(cam)
    db.commit()
    db.refresh(cam)
    _sync_camera_to_agent(cam)
    _reload_zones_for_camera(cam.id, db)
    return cam


@router.delete("/{camera_id}")
def delete_camera(
    camera_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    cam = db.query(Camera).filter(
        Camera.id == camera_id, Camera.user_id == current_user.id
    ).first()
    if not cam:
        raise HTTPException(404, "Camera not found")
    detection_agent.remove_camera(camera_id)
    db.delete(cam)
    db.commit()
    return {"ok": True}


@router.patch("/{camera_id}", response_model=CameraOut)
def edit_camera(
    camera_id: int,
    payload: CameraUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Edit a camera's name and/or source URL without deleting and re-adding it."""
    cam = db.query(Camera).filter(
        Camera.id == camera_id, Camera.user_id == current_user.id
    ).first()
    if not cam:
        raise HTTPException(404, "Camera not found")

    source_changed = payload.source is not None and payload.source.strip() != cam.source.strip()

    if payload.name is not None:
        cam.name = payload.name.strip()
    if payload.source is not None:
        cam.source = payload.source.strip()

    db.commit()
    db.refresh(cam)

    # If the source URL changed, hot-swap the camera in the detection agent
    if source_changed:
        detection_agent.remove_camera(camera_id)
        detection_agent.add_camera(cam.id, cam.source, name=cam.name)
        _reload_zones_for_camera(cam.id, db)
    elif payload.name is not None:
        # Name-only change: just update the registry, no capture restart needed
        from agents.detection_agent import register_camera_name
        register_camera_name(camera_id, cam.name)

    status = detection_agent.get_camera_status(camera_id)
    return {
        "id": cam.id,
        "name": cam.name,
        "source": cam.source,
        "status": status,
        "created_at": cam.created_at,
    }


@router.get("/{camera_id}/status")
def camera_status(
    camera_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    cam = db.query(Camera).filter(
        Camera.id == camera_id, Camera.user_id == current_user.id
    ).first()
    if not cam:
        raise HTTPException(404, "Camera not found")
    status = detection_agent.get_camera_status(camera_id)
    return {"camera_id": camera_id, "status": status}


@router.post("/{camera_id}/test")
def test_camera(payload: CameraCreate):
    """Test if a camera source is accessible before saving."""
    src = payload.source.strip()
    cap = cv2.VideoCapture(int(src) if src.isdigit() else src)
    ok = cap.isOpened()
    if ok:
        ret, _ = cap.read()
        ok = ret
    cap.release()
    return {"accessible": ok}


@router.post("/{camera_id}/pause")
def pause_camera(
    camera_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Pause a specific camera — stops its capture thread and disables retries."""
    cam = db.query(Camera).filter(
        Camera.id == camera_id, Camera.user_id == current_user.id
    ).first()
    if not cam:
        raise HTTPException(404, "Camera not found")
    detection_agent.pause_camera(camera_id)
    return {"camera_id": camera_id, "status": "disabled"}


@router.post("/{camera_id}/resume")
def resume_camera(
    camera_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Resume a paused camera."""
    cam = db.query(Camera).filter(
        Camera.id == camera_id, Camera.user_id == current_user.id
    ).first()
    if not cam:
        raise HTTPException(404, "Camera not found")
    detection_agent.resume_camera(camera_id)
    return {"camera_id": camera_id, "status": "online"}


@router.get("/{camera_id}/telemetry")
def get_camera_telemetry(
    camera_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get live AI pipeline telemetry, active trackers, FSM behavior states,
    brightness/contrast metrics, and active pipelines for a specific camera.
    """
    import numpy as np
    cam = db.query(Camera).filter(
        Camera.id == camera_id, Camera.user_id == current_user.id
    ).first()
    if not cam:
        raise HTTPException(404, "Camera not found")

    urgency = detection_agent._scheduler.get_score(camera_id)
    result = detection_agent.get_result(camera_id)
    detections = result.detections if result else []

    person_count = sum(1 for d in detections if d.get("class_name") == "person")
    vehicle_count = sum(1 for d in detections if d.get("class_name") != "person")

    from agents.decision_agent import decision_agent
    active_objects = []
    for d in detections:
        tid = d.get("track_id")
        key = (camera_id, tid)
        state_obj = decision_agent._states.get(key)

        state_name = state_obj.fsm_state.value if state_obj and hasattr(state_obj.fsm_state, "value") else (state_obj.fsm_state if state_obj else "IDLE")
        identity = state_obj.identity if state_obj else "UNKNOWN"
        duration = 0.0
        if state_obj:
            if hasattr(state_obj, "duration_seconds") and state_obj.duration_seconds > 0:
                duration = state_obj.duration_seconds
            elif hasattr(state_obj, "last_observation_time") and hasattr(state_obj, "first_observation_time"):
                duration = state_obj.last_observation_time - state_obj.first_observation_time

        active_objects.append({
            "track_id": tid,
            "class_name": d.get("class_name"),
            "confidence": d.get("confidence"),
            "bbox": d.get("bbox"),
            "fsm_state": state_name,
            "identity": identity,
            "duration_seconds": duration,
        })

    frame = detection_agent.get_snapshot(camera_id)
    brightness = 0.0
    contrast = 0.0
    lighting_condition = "Unknown"

    if frame is not None:
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            brightness = float(np.mean(gray))
            contrast = float(np.std(gray))
            if brightness < 50:
                lighting_condition = "Low Light (Night Mode)"
            elif brightness < 100:
                lighting_condition = "Dim (Twilight/Indoor)"
            else:
                lighting_condition = "Normal (Well-lit / Daylight)"
        except Exception:
            pass

    from utils import face_utils
    pipelines = {
        "yolo_object_tracker": {
            "status": "active",
            "model_name": "YOLOv8n",
            "resolution": "640x640 (dynamic projection)",
        },
        "arcface_biometrics": {
            "status": "active" if face_utils.is_available() else "disabled",
            "model_name": "ArcFace (ResNet100)",
            "enrolled_faces": len(decision_agent._enrolled_faces),
        },
        "color_classifier": {
            "status": "active",
            "model_name": "C++ OpenCV K-Means (k=5)",
        },
        "fsm_behavior_engine": {
            "status": "active",
            "states_tracked": len(decision_agent._states),
        },
        "scheduler_deduplicator": {
            "status": "active",
            "urgency_score": round(urgency, 3),
            "stale_drop_threshold": "500ms (stale-drop)",
        }
    }

    return {
        "camera_id": camera_id,
        "camera_name": cam.name,
        "status": detection_agent.get_camera_status(camera_id),
        "person_count": person_count,
        "vehicle_count": vehicle_count,
        "total_active_tracks": len(active_objects),
        "active_objects": active_objects,
        "environment": {
            "brightness": round(brightness, 1),
            "contrast": round(contrast, 1),
            "lighting": lighting_condition,
        },
        "pipelines": pipelines,
    }


def _reload_zones_for_camera(camera_id: int, db: Session):
    from database import Zone
    from agents.decision_agent import decision_agent
    zones = db.query(Zone).filter(Zone.camera_id == camera_id).all()
    decision_agent.set_zones(camera_id, [
        {
            "id": z.id, "name": z.name, "zone_type": z.zone_type,
            "points_json": z.points_json, "config_json": z.config_json,
            "active": z.active,
        }
        for z in zones
    ])

