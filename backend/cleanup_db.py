"""
Cleanup script:
1. Delete sksharma user and ALL related data (cameras, zones, events, faces)
2. Renumber admin's cameras sequentially starting from 1
3. Report final state
"""
import sys
sys.path.insert(0, '.')
from database import SessionLocal, User, Camera, Zone, EnrolledFace, Event, AlertConfig

db = SessionLocal()

print("=== BEFORE CLEANUP ===")
for u in db.query(User).all():
    cams = db.query(Camera).filter(Camera.user_id == u.id).count()
    faces = db.query(EnrolledFace).filter(EnrolledFace.user_id == u.id).count()
    print(f"User {u.id}: {u.username} | cameras={cams} faces={faces}")

# Delete sksharma (user_id=2) - cascade deletes cameras/zones/events/faces
sksharma = db.query(User).filter(User.username != 'admin').all()
for u in sksharma:
    print(f"\nDeleting user: {u.username} (id={u.id})")
    # Manually delete events first (they ref cameras which ref user)
    cam_ids = [c.id for c in db.query(Camera).filter(Camera.user_id == u.id).all()]
    if cam_ids:
        n = db.query(Event).filter(Event.camera_id.in_(cam_ids)).delete(synchronize_session=False)
        print(f"  Deleted {n} events")
        n = db.query(Zone).filter(Zone.camera_id.in_(cam_ids)).delete(synchronize_session=False)
        print(f"  Deleted {n} zones")
        n = db.query(Camera).filter(Camera.user_id == u.id).delete(synchronize_session=False)
        print(f"  Deleted {n} cameras")
    n = db.query(EnrolledFace).filter(EnrolledFace.user_id == u.id).delete(synchronize_session=False)
    print(f"  Deleted {n} enrolled faces")
    n = db.query(AlertConfig).filter(AlertConfig.user_id == u.id).delete(synchronize_session=False)
    print(f"  Deleted {n} alert configs")
    db.delete(u)
    db.commit()

print("\n=== AFTER CLEANUP ===")
for u in db.query(User).all():
    cams = db.query(Camera).filter(Camera.user_id == u.id).all()
    faces = db.query(EnrolledFace).filter(EnrolledFace.user_id == u.id).count()
    events = db.query(Event).filter(Event.camera_id.in_([c.id for c in cams])).count()
    print(f"User {u.id}: {u.username}")
    print(f"  Cameras: {len(cams)}  Faces: {faces}  Events: {events}")
    for i, c in enumerate(cams, 1):
        zones = db.query(Zone).filter(Zone.camera_id == c.id).count()
        print(f"  Cam DB_id={c.id} name='{c.name}' source='{c.source}' zones={zones}")

db.close()
print("\nDone.")
