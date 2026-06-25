import sys
import os
import cv2
import json
import logging
from pathlib import Path

# Add parent directory to path so database and utils can be imported correctly
parent_dir = str(Path(__file__).parent.parent)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from database import SessionLocal, EnrolledFace
from utils import face_utils

logger = logging.getLogger(__name__)

def run_migration():
    logger.info("Starting biometric database migration to ONNX ArcFace...")
    
    # Ensure model is initialized
    if not face_utils.is_available():
        logger.error("ONNX ArcFace model is not available. Skipping migration.")
        return
        
    db = SessionLocal()
    try:
        enrolled_faces = db.query(EnrolledFace).all()
        if not enrolled_faces:
            logger.info("No enrolled faces found in the database. Nothing to migrate.")
            return
            
        migrated_count = 0
        for face in enrolled_faces:
            photo_path = face.photo_path
            if not photo_path or not os.path.exists(photo_path):
                logger.warning(f"Photo path '{photo_path}' for user '{face.name}' (ID: {face.id}) does not exist. Cannot migrate.")
                continue
                
            img = cv2.imread(photo_path)
            if img is None:
                logger.error(f"Failed to load image at '{photo_path}' for user '{face.name}'. Skipping.")
                continue
                
            new_emb = face_utils.extract_embedding_for_enrollment(img)
            if new_emb is None:
                logger.error(f"Failed to extract ONNX face embedding for user '{face.name}' from '{photo_path}'. Skipping.")
                continue
                
            face.encoding_json = json.dumps(new_emb.tolist())
            migrated_count += 1
            logger.info(f"Successfully migrated biometric signature for '{face.name}' (ID: {face.id})")
            
        if migrated_count > 0:
            db.commit()
            logger.info(f"Completed biometric database migration. Successfully updated {migrated_count} records.")
        else:
            logger.info("No biometric records were updated.")
            
    except Exception as e:
        db.rollback()
        logger.error(f"Biometric migration failed with error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    run_migration()
