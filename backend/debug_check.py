import sys, time, cv2, numpy as np
sys.path.insert(0, '.')

print("=== TEST 1: YOLO inference on webcam frame ===")
from ultralytics import YOLO
model = YOLO('yolov8n.pt')

# Try to get real webcam frame
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
frame = None
if cap.isOpened():
    ret, frame = cap.read()
    cap.release()
    if ret:
        print(f"Got webcam frame: {frame.shape}")
    else:
        print("Webcam opened but read failed")
else:
    print("Webcam not accessible - using blank frame")
    frame = np.zeros((480, 640, 3), dtype=np.uint8)

# Run at low confidence to see anything
for conf in [0.25, 0.15]:
    results = model.track(frame, persist=True, conf=conf, verbose=False, tracker='bytetrack.yaml')
    boxes = results[0].boxes
    n = len(boxes) if boxes is not None else 0
    print(f"YOLO conf={conf} detected {n} objects")
    if n > 0:
        for i in range(min(n, 5)):
            cls = int(boxes.cls[i])
            c = float(boxes.conf[i])
            name = model.names.get(cls, '?')
            tid = int(boxes.id[i]) if boxes.id is not None else -1
            print(f"  -> #{tid} {name} conf={c:.2f}")
        break

print()
print("=== TEST 2: DB state ===")
from database import SessionLocal, Camera, Zone, Event
db = SessionLocal()
cams = db.query(Camera).all()
print(f"Total cameras: {len(cams)}")
for c in cams:
    zones = db.query(Zone).filter(Zone.camera_id == c.id).all()
    n_events = db.query(Event).filter(Event.camera_id == c.id).count()
    active_zones = [z for z in zones if z.active]
    print(f"  Cam {c.id} name='{c.name}' user_id={c.user_id} source='{c.source}' zones={len(zones)} (active={len(active_zones)}) events={n_events}")
    for z in zones:
        print(f"    Zone {z.id}: '{z.name}' type={z.zone_type} active={z.active}")

print()
print("=== TEST 3: Recent events + evidence frames ===")
from agents.detection_agent import get_evidence_frame
events = db.query(Event).order_by(Event.id.desc()).limit(10).all()
print(f"Total recent events: {len(events)}")
for e in events:
    frame_bytes = get_evidence_frame(e.frame_path) if e.frame_path else None
    print(f"  Event {e.id}: type={e.event_type} cam={e.camera_id} frame_key={e.frame_path!r} in_memory={frame_bytes is not None}")

print()
print("=== TEST 4: DeepFace availability ===")
from utils import face_utils
avail = face_utils.is_available()
print(f"DeepFace available: {avail}")

from database import EnrolledFace
faces = db.query(EnrolledFace).all()
print(f"Enrolled faces in DB: {len(faces)}")
for f in faces:
    print(f"  Face: name='{f.name}' user_id={f.user_id}")

db.close()
print()
print("=== DONE ===")
