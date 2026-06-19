from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, cast, String
from typing import List, Optional
from datetime import datetime, timedelta
from database import get_db, Event, Camera, User
from auth import get_current_user
from models.schemas import EventOut

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=List[dict])
def list_events(
    camera_id: Optional[int] = Query(None),
    risk_level: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    owned_ids = [c.id for c in db.query(Camera).filter(Camera.user_id == current_user.id).all()]
    q = db.query(Event).options(joinedload(Event.camera), joinedload(Event.zone)).filter(Event.camera_id.in_(owned_ids))
    if camera_id:
        q = q.filter(Event.camera_id == camera_id)
    if risk_level:
        q = q.filter(Event.risk_level == risk_level.upper())
    events = q.order_by(Event.timestamp.desc()).offset(offset).limit(limit).all()
    return [EventOut.model_validate(e).model_dump() for e in events]


@router.get("/{event_id}", response_model=dict)
def get_event(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    owned_ids = [c.id for c in db.query(Camera).filter(Camera.user_id == current_user.id).all()]
    event = db.query(Event).options(joinedload(Event.camera), joinedload(Event.zone)).filter(
        Event.id == event_id, Event.camera_id.in_(owned_ids)
    ).first()
    if not event:
        raise HTTPException(404, "Event not found")
    return EventOut.model_validate(event).model_dump()


@router.get("/{event_id}/frame")
def get_event_frame(
    event_id: int,
    token: str = Query(...),
    db: Session = Depends(get_db)
):
    """
    Return the evidence JPEG for this event.
    """
    from auth import decode_token
    payload = decode_token(token)
    if not payload:
        raise HTTPException(401, "Invalid token")
    user_id = payload.get("sub")

    from fastapi.responses import RedirectResponse
    owned_ids = [c.id for c in db.query(Camera).filter(Camera.user_id == user_id).all()]
    event = db.query(Event).filter(Event.id == event_id, Event.camera_id.in_(owned_ids)).first()
    if not event or not event.frame_path:
        raise HTTPException(404, "Frame not available")

    # 1. Try in-memory cache
    from agents.detection_agent import get_evidence_frame
    jpeg = get_evidence_frame(event.frame_path)
    if jpeg:
        return Response(content=jpeg, media_type="image/jpeg")

    # 2. Redirect to static file (always written to disk at capture time)
    return RedirectResponse(url=f"/frames/{event.frame_path}.jpg")


@router.get("/{event_id}/frame/save")
def save_event_frame(
    event_id: int,
    token: str = Query(...),
    db: Session = Depends(get_db)
):
    """
    Download the evidence frame as a JPEG file.
    """
    from auth import decode_token
    payload = decode_token(token)
    if not payload:
        raise HTTPException(401, "Invalid token")
    user_id = payload.get("sub")

    owned_ids = [c.id for c in db.query(Camera).filter(Camera.user_id == user_id).all()]
    event = db.query(Event).filter(Event.id == event_id, Event.camera_id.in_(owned_ids)).first()
    if not event or not event.frame_path:
        raise HTTPException(404, "Frame not available")

    from agents.detection_agent import get_evidence_frame
    jpeg = get_evidence_frame(event.frame_path)
    if not jpeg:
        raise HTTPException(404, "Frame expired. Only available during the current session.")

    filename = f"sentinel_event_{event_id}_{event.event_type}.jpg"
    return Response(
        content=jpeg,
        media_type="image/jpeg",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.delete("/{event_id}")
def delete_event(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    owned_ids = [c.id for c in db.query(Camera).filter(Camera.user_id == current_user.id).all()]
    event = db.query(Event).filter(Event.id == event_id, Event.camera_id.in_(owned_ids)).first()
    if not event:
        raise HTTPException(404, "Event not found")
    db.delete(event)
    db.commit()
    return {"ok": True}


@router.delete("")
def clear_events(
    camera_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    owned_ids = [c.id for c in db.query(Camera).filter(Camera.user_id == current_user.id).all()]
    q = db.query(Event).filter(Event.camera_id.in_(owned_ids))
    if camera_id:
        q = q.filter(Event.camera_id == camera_id)
    count = q.count()
    q.delete(synchronize_session=False)
    db.commit()
    return {"deleted": count}


# ── V4 Enhanced Search ────────────────────────────────────────────────────────
@router.get("/search", response_model=List[dict])
def search_events(
    q: Optional[str] = Query(None, description="Free text search across identity, colors, object_details"),
    camera_id: Optional[int] = Query(None),
    object_class: Optional[str] = Query(None, description="person, car, truck, motorcycle, bus"),
    identity: Optional[str] = Query(None, description="Exact or partial name match"),
    color: Optional[str] = Query(None, description="Search dominant_colors (e.g. red, blue)"),
    risk_level: Optional[str] = Query(None),
    fsm_state: Optional[str] = Query(None, description="IDLE, ENTERING, PRESENT, LOITERING, THREAT"),
    direction: Optional[str] = Query(None, description="entering, exiting, stationary, crossing"),
    date_from: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Search events with multiple filters. All filters are AND-combined."""
    owned_ids = [c.id for c in db.query(Camera).filter(Camera.user_id == current_user.id).all()]
    if not owned_ids:
        return []

    query = db.query(Event).options(
        joinedload(Event.camera), joinedload(Event.zone)
    ).filter(Event.camera_id.in_(owned_ids))

    if camera_id:
        query = query.filter(Event.camera_id == camera_id)
    if object_class:
        query = query.filter(Event.object_class == object_class)
    if identity:
        query = query.filter(Event.identity.ilike(f"%{identity}%"))
    if color:
        query = query.filter(Event.dominant_colors.ilike(f"%{color.lower()}%"))
    if risk_level:
        query = query.filter(Event.risk_level == risk_level.upper())
    if fsm_state:
        query = query.filter(Event.fsm_state == fsm_state.upper())
    if direction:
        query = query.filter(Event.direction == direction.lower())
    if date_from:
        try:
            dt_from = datetime.strptime(date_from, "%Y-%m-%d")
            query = query.filter(Event.timestamp >= dt_from)
        except ValueError:
            raise HTTPException(400, f"Invalid date_from: '{date_from}'. Expected YYYY-MM-DD.")
    if date_to:
        try:
            dt_to = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(Event.timestamp < dt_to)
        except ValueError:
            raise HTTPException(400, f"Invalid date_to: '{date_to}'. Expected YYYY-MM-DD.")

    # Free text search across multiple fields
    if q:
        text_filter = f"%{q}%"
        query = query.filter(
            (Event.identity.ilike(text_filter)) |
            (Event.dominant_colors.ilike(text_filter)) |
            (Event.object_details.ilike(text_filter)) |
            (Event.object_class.ilike(text_filter)) |
            (Event.event_type.ilike(text_filter))
        )

    events = query.order_by(Event.timestamp.desc()).offset(offset).limit(limit).all()
    return [EventOut.model_validate(e).model_dump() for e in events]


@router.get("/stats")
def event_stats(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    camera_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Return aggregate event statistics for dashboards and reports."""
    owned_ids = [c.id for c in db.query(Camera).filter(Camera.user_id == current_user.id).all()]
    if not owned_ids:
        return {"total_events": 0}

    query = db.query(Event).filter(Event.camera_id.in_(owned_ids))

    if camera_id:
        query = query.filter(Event.camera_id == camera_id)
    if date_from:
        try:
            query = query.filter(Event.timestamp >= datetime.strptime(date_from, "%Y-%m-%d"))
        except ValueError:
            pass
    if date_to:
        try:
            query = query.filter(Event.timestamp < datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1))
        except ValueError:
            pass

    events = query.all()

    # Aggregate stats
    total = len(events)
    persons = sum(1 for e in events if e.object_class == "person")
    vehicles = sum(1 for e in events if e.object_class != "person")
    known = sum(1 for e in events if e.identity and e.identity != "UNKNOWN")
    alerts = sum(1 for e in events if e.risk_level in ("HIGH", "CRITICAL"))

    # Events by risk level
    by_risk = {}
    for e in events:
        by_risk[e.risk_level] = by_risk.get(e.risk_level, 0) + 1

    # Events by camera
    by_camera = {}
    for e in events:
        by_camera[e.camera_id] = by_camera.get(e.camera_id, 0) + 1

    # Events by hour
    by_hour = {f"{h:02d}": 0 for h in range(24)}
    for e in events:
        if e.timestamp:
            by_hour[f"{e.timestamp.hour:02d}"] += 1

    # Peak hour
    peak_hour = max(by_hour, key=by_hour.get) if events else None

    return {
        "total_events": total,
        "total_persons": persons,
        "total_vehicles": vehicles,
        "known_persons": known,
        "unknown_persons": persons - known,
        "alerts_triggered": alerts,
        "peak_hour": peak_hour,
        "by_risk_level": by_risk,
        "by_camera": by_camera,
        "hourly_activity": by_hour,
    }

