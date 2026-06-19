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

