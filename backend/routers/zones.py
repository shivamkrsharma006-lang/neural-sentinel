from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from database import get_db, Zone, Camera, User
from auth import get_current_user
from models.schemas import ZoneCreate, ZoneOut
from agents.decision_agent import decision_agent

router = APIRouter(prefix="/cameras/{camera_id}/zones", tags=["zones"])


def _reload(camera_id: int, db: Session):
    zones = db.query(Zone).filter(Zone.camera_id == camera_id).all()
    decision_agent.reload_zones(camera_id, [
        {
            "id": z.id, "name": z.name, "zone_type": z.zone_type,
            "points_json": z.points_json, "config_json": z.config_json,
            "active": z.active,
        }
        for z in zones
    ])


def _owned_camera(camera_id: int, user_id: int, db: Session) -> Camera:
    cam = db.query(Camera).filter(Camera.id == camera_id, Camera.user_id == user_id).first()
    if not cam:
        raise HTTPException(404, "Camera not found")
    return cam


@router.get("", response_model=List[ZoneOut])
def list_zones(
    camera_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    _owned_camera(camera_id, current_user.id, db)
    return db.query(Zone).filter(Zone.camera_id == camera_id).all()


@router.post("", response_model=ZoneOut)
def create_zone(
    camera_id: int,
    payload: ZoneCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    _owned_camera(camera_id, current_user.id, db)
    zone = Zone(
        camera_id=camera_id,
        name=payload.name,
        zone_type=payload.zone_type,
        points_json=payload.points_json,
        config_json=payload.config_json,
    )
    db.add(zone)
    db.commit()
    db.refresh(zone)
    _reload(camera_id, db)
    return zone


@router.put("/{zone_id}", response_model=ZoneOut)
def update_zone(
    camera_id: int,
    zone_id: int,
    payload: ZoneCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    _owned_camera(camera_id, current_user.id, db)
    zone = db.query(Zone).filter(Zone.id == zone_id, Zone.camera_id == camera_id).first()
    if not zone:
        raise HTTPException(404, "Zone not found")
    zone.name = payload.name
    zone.zone_type = payload.zone_type
    zone.points_json = payload.points_json
    zone.config_json = payload.config_json
    db.commit()
    db.refresh(zone)
    _reload(camera_id, db)
    return zone


@router.patch("/{zone_id}/toggle")
def toggle_zone(
    camera_id: int,
    zone_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    _owned_camera(camera_id, current_user.id, db)
    zone = db.query(Zone).filter(Zone.id == zone_id, Zone.camera_id == camera_id).first()
    if not zone:
        raise HTTPException(404, "Zone not found")
    zone.active = not zone.active
    db.commit()
    _reload(camera_id, db)
    return {"zone_id": zone_id, "active": zone.active}


@router.delete("/{zone_id}")
def delete_zone(
    camera_id: int,
    zone_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    _owned_camera(camera_id, current_user.id, db)
    zone = db.query(Zone).filter(Zone.id == zone_id, Zone.camera_id == camera_id).first()
    if not zone:
        raise HTTPException(404, "Zone not found")
    db.delete(zone)
    db.commit()
    _reload(camera_id, db)
    return {"ok": True}
