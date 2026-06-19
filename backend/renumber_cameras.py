"""
Renumber cameras cleanly:
- Rename camera names to 'Camera 1', 'Camera 2' etc based on their creation order
- Does NOT change DB primary keys (that requires CASCADE updates)
- Just makes the display names sequential and clean
"""
import sys
sys.path.insert(0, '.')
from database import SessionLocal, Camera, Zone, Event, EnrolledFace

db = SessionLocal()

cameras = db.query(Camera).filter(Camera.user_id == 1).order_by(Camera.id).all()
print(f"Found {len(cameras)} cameras for admin:")
for i, cam in enumerate(cameras, 1):
    old_name = cam.name
    new_name = f"Camera {i}"
    cam.name = new_name
    print(f"  DB id={cam.id}: '{old_name}' -> '{new_name}' (source={cam.source})")

db.commit()

# Delete all old events (they have wrong timezone data and confusing zone names)
print("\nCleaning up old events...")
cam_ids = [c.id for c in cameras]
n = db.query(Event).filter(Event.camera_id.in_(cam_ids)).delete(synchronize_session=False)
db.commit()
print(f"Deleted {n} old events (fresh start — new events will have correct timestamps)")

# Show final state
print("\n=== Final State ===")
for cam in db.query(Camera).filter(Camera.user_id == 1).order_by(Camera.id).all():
    zones = db.query(Zone).filter(Zone.camera_id == cam.id).all()
    print(f"  DB id={cam.id} name='{cam.name}' source='{cam.source}'")
    for z in zones:
        print(f"    Zone: '{z.name}' type={z.zone_type} active={z.active}")

db.close()
print("\nDone. Restart backend to reload camera names.")
