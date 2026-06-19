import json
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List
import cv2

from database import get_db, EnrolledFace, User
from auth import get_current_user
from models.schemas import FaceOut
from utils import face_utils
from agents.decision_agent import decision_agent

router = APIRouter(prefix="/faces", tags=["faces"])


def _reload_faces(db: Session):
    """Push all enrolled face embeddings into the decision agent."""
    faces = db.query(EnrolledFace).all()
    encoded = []
    for f in faces:
        try:
            emb = np.array(json.loads(f.encoding_json), dtype=np.float32)
            encoded.append((f.name, emb))
        except Exception:
            pass
    decision_agent.set_enrolled_faces(encoded)


@router.get("", response_model=List[FaceOut])
def list_faces(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return db.query(EnrolledFace).filter(EnrolledFace.user_id == current_user.id).all()


@router.post("", response_model=FaceOut)
async def enroll_face(
    name: str = Form(...),
    photo: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not face_utils.is_available():
        raise HTTPException(503, "Face recognition not available. Install insightface.")
    image_bytes = await photo.read()
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "Could not decode image")
    embedding = face_utils.extract_embedding_for_enrollment(img)
    if embedding is None:
        raise HTTPException(400, "No face detected in the uploaded image. Please use a clear frontal photo with good lighting.")
    # Save photo
    from config import FRAMES_DIR
    photo_path = str(FRAMES_DIR / f"face_{current_user.id}_{name.replace(' ','_')}.jpg")
    cv2.imwrite(photo_path, img)
    face_record = EnrolledFace(
        user_id=current_user.id,
        name=name,
        encoding_json=json.dumps(embedding.tolist()),
        photo_path=photo_path,
    )
    db.add(face_record)
    db.commit()
    db.refresh(face_record)
    _reload_faces(db)
    return face_record


@router.delete("/{face_id}")
def delete_face(
    face_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    face = db.query(EnrolledFace).filter(
        EnrolledFace.id == face_id, EnrolledFace.user_id == current_user.id
    ).first()
    if not face:
        raise HTTPException(404, "Face not found")
    db.delete(face)
    db.commit()
    _reload_faces(db)
    return {"ok": True}


@router.get("/status")
def face_recognition_status():
    return {
        "available": face_utils.is_available(),
        "message": "InsightFace ready" if face_utils.is_available() else "InsightFace not installed"
    }
