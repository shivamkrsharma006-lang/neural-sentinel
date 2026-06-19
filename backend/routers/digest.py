from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from datetime import datetime, timedelta
from collections import defaultdict
from database import get_db, Event, Camera, Zone, User
from auth import get_current_user

router = APIRouter(prefix="/digest", tags=["digest"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date(date_str: str) -> datetime:
    """Parse an ISO date string (YYYY-MM-DD) into a datetime at midnight."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, f"Invalid date format: '{date_str}'. Expected YYYY-MM-DD.")


def _get_owned_camera_ids(db: Session, user_id: int) -> List[int]:
    """Return the list of camera IDs owned by *user_id*."""
    return [c.id for c in db.query(Camera).filter(Camera.user_id == user_id).all()]


def _get_camera_name_map(db: Session, camera_ids: List[int]) -> dict:
    """Return a {camera_id: camera_name} mapping for quick lookups."""
    cameras = db.query(Camera).filter(Camera.id.in_(camera_ids)).all()
    return {c.id: c.name for c in cameras}


def _build_digest(events: List[Event], camera_names: dict) -> dict:
    """
    Build the full digest payload from a list of Event ORM objects.

    Returns a dict with:
      - identity_groups  : per-identity breakdown
      - aggregate_stats  : total counts, peak hour, etc.
      - notable_events   : HIGH / CRITICAL events
      - hourly_activity  : {"00": n, "01": n, …, "23": n}
    """
    # Fast path – no events at all
    if not events:
        return {
            "identity_groups": [],
            "aggregate_stats": {
                "total_persons": 0,
                "known_persons": 0,
                "unknown_persons": 0,
                "total_vehicles": 0,
                "total_events": 0,
                "alerts_triggered": 0,
                "peak_hour": None,
            },
            "notable_events": [],
            "hourly_activity": {f"{h:02d}": 0 for h in range(24)},
        }

    # ---- per-identity grouping ----
    groups = defaultdict(list)
    for e in events:
        groups[e.identity].append(e)

    identity_groups = []
    for identity, group_events in groups.items():
        timestamps = [e.timestamp for e in group_events]
        first_seen = min(timestamps)
        last_seen = max(timestamps)
        duration_seconds = (last_seen - first_seen).total_seconds()

        # cameras & zones this identity appeared in
        cameras_seen = sorted({
            camera_names.get(e.camera_id, f"camera-{e.camera_id}")
            for e in group_events
        })
        zones_seen = sorted({
            e.zone.name for e in group_events if e.zone is not None
        })

        risk_scores = [e.risk_score for e in group_events if e.risk_score is not None]
        avg_risk = round(sum(risk_scores) / len(risk_scores), 3) if risk_scores else 0.0

        event_types = sorted({e.event_type for e in group_events})

        identity_groups.append({
            "identity": identity,
            "object_class": group_events[0].object_class,
            "first_seen": first_seen.isoformat(),
            "last_seen": last_seen.isoformat(),
            "duration_seconds": duration_seconds,
            "cameras": cameras_seen,
            "zones": zones_seen,
            "event_count": len(group_events),
            "avg_risk_score": avg_risk,
            "event_types": event_types,
        })

    # Sort groups: CRITICAL/HIGH identities first, then by event count desc
    identity_groups.sort(key=lambda g: g["event_count"], reverse=True)

    # ---- aggregate stats ----
    person_identities = [g for g in identity_groups if g["object_class"] == "person"]
    known = [g for g in person_identities if g["identity"] != "UNKNOWN"]
    unknown = [g for g in person_identities if g["identity"] == "UNKNOWN"]
    vehicle_groups = [g for g in identity_groups if g["object_class"] != "person"]

    alerts_triggered = sum(
        1 for e in events if e.risk_level in ("HIGH", "CRITICAL")
    )

    # peak hour
    hourly_counts: dict[str, int] = {f"{h:02d}": 0 for h in range(24)}
    for e in events:
        hourly_counts[f"{e.timestamp.hour:02d}"] += 1
    peak_hour = max(hourly_counts, key=hourly_counts.get)  # type: ignore[arg-type]

    aggregate_stats = {
        "total_persons": len(person_identities),
        "known_persons": len(known),
        "unknown_persons": len(unknown),
        "total_vehicles": len(vehicle_groups),
        "total_events": len(events),
        "alerts_triggered": alerts_triggered,
        "peak_hour": peak_hour,
    }

    # ---- notable events (HIGH / CRITICAL) ----
    notable_events = []
    for e in events:
        if e.risk_level in ("HIGH", "CRITICAL"):
            notable_events.append({
                "event_id": e.id,
                "event_type": e.event_type,
                "risk_level": e.risk_level,
                "risk_score": e.risk_score,
                "identity": e.identity,
                "object_class": e.object_class,
                "camera": camera_names.get(e.camera_id, f"camera-{e.camera_id}"),
                "zone": e.zone.name if e.zone else None,
                "timestamp": e.timestamp.isoformat(),
            })
    notable_events.sort(key=lambda n: n["timestamp"], reverse=True)

    return {
        "identity_groups": identity_groups,
        "aggregate_stats": aggregate_stats,
        "notable_events": notable_events,
        "hourly_activity": hourly_counts,
    }


def _fetch_events(
    db: Session,
    owned_ids: List[int],
    start: datetime,
    end: datetime,
    camera_id: Optional[int] = None,
) -> List[Event]:
    """Query events for *owned_ids* within [start, end), optionally filtered by camera."""
    q = (
        db.query(Event)
        .options(joinedload(Event.camera), joinedload(Event.zone))
        .filter(Event.camera_id.in_(owned_ids))
        .filter(Event.timestamp >= start)
        .filter(Event.timestamp < end)
    )
    if camera_id is not None:
        if camera_id not in owned_ids:
            raise HTTPException(403, "Camera not owned by current user")
        q = q.filter(Event.camera_id == camera_id)
    return q.order_by(Event.timestamp.asc()).all()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
def get_digest(
    date: str = Query(..., description="ISO date string, e.g. '2024-06-15'"),
    camera_id: Optional[int] = Query(None, description="Filter to a specific camera"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Generate an activity digest for a single day.

    Returns per-identity breakdowns, aggregate statistics, notable events,
    and an hourly activity histogram.
    """
    start_of_day = _parse_date(date)
    end_of_day = start_of_day + timedelta(days=1)

    owned_ids = _get_owned_camera_ids(db, current_user.id)
    if not owned_ids:
        return _build_digest([], {})

    camera_names = _get_camera_name_map(db, owned_ids)
    events = _fetch_events(db, owned_ids, start_of_day, end_of_day, camera_id)

    digest = _build_digest(events, camera_names)
    digest["date"] = date
    return digest


@router.get("/range")
def get_digest_range(
    date_from: str = Query(..., description="Start date (inclusive), e.g. '2024-06-10'"),
    date_to: str = Query(..., description="End date (inclusive), e.g. '2024-06-15'"),
    camera_id: Optional[int] = Query(None, description="Filter to a specific camera"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Generate an activity digest spanning multiple days.

    *date_from* and *date_to* are both inclusive.  Returns the same structure
    as the single-day digest, plus a ``date_from`` / ``date_to`` header.
    """
    start = _parse_date(date_from)
    end = _parse_date(date_to) + timedelta(days=1)  # inclusive upper bound

    if start >= end:
        raise HTTPException(400, "date_from must be before date_to")

    owned_ids = _get_owned_camera_ids(db, current_user.id)
    if not owned_ids:
        return _build_digest([], {})

    camera_names = _get_camera_name_map(db, owned_ids)
    events = _fetch_events(db, owned_ids, start, end, camera_id)

    digest = _build_digest(events, camera_names)
    digest["date_from"] = date_from
    digest["date_to"] = date_to
    return digest
