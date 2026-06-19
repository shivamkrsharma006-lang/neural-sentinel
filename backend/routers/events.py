from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
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
