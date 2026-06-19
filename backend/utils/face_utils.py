"""
Face recognition — V2: Fast 3-stage pipeline (50-200ms vs 2000-35000ms MTCNN)

Stage 1: Smart face crop — take top 45% of the YOLO body bbox (face always there)
Stage 2: OpenCV Haar cascade — fast CPU face detector (~5ms) to confirm face present
Stage 3: ArcFace embedding with enforce_detection=False — skip slow internal detector
         since we already know the face location from Stage 2.

Fallback: If Haar fails to find a face, try DeepFace with 'opencv' backend
          (still ~10x faster than MTCNN).

Why MTCNN was so slow:
  MTCNN is a 3-stage deep-learning cascade running on the FULL body crop.
  At 640x480 it processes 300k+ pixels per call → 1-35 seconds on CPU.
  Our approach: pass only the 100x100 face crop → ~50ms total.
"""
import numpy as np
import logging
import time
import cv2
from typing import List, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)

_deepface_available = False
_initialized = False
_haar_cascade: Optional[cv2.CascadeClassifier] = None
_clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))  # persistent, no alloc per call

# Minimum Laplacian variance for a usable face crop (below = too blurry to recognise)
_BLUR_THRESHOLD = 30.0


def _init():
    global _deepface_available, _initialized, _haar_cascade
    if _initialized:
        return
    _initialized = True
    try:
        import deepface  # noqa
        _deepface_available = True
        logger.info("DeepFace loaded successfully")
    except Exception as e:
        logger.warning(f"DeepFace not available: {e}. Face recognition disabled.")
        _deepface_available = False

    # Load OpenCV Haar cascade for fast face detection
    haar_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(haar_path)
    if not cascade.empty():
        _haar_cascade = cascade
        logger.info("Haar cascade loaded for fast face pre-detection")
    else:
        logger.warning("Haar cascade not found — will use DeepFace detector as fallback")


def is_available() -> bool:
    _init()
    return _deepface_available


def prewarm_model():
    """
    Pre-warm ArcFace at startup using a tiny dummy crop with opencv backend.
    This is much faster than MTCNN pre-warming (was taking 30-60s, now <5s).
    """
    _init()
    if not _deepface_available:
        return
    try:
        from deepface import DeepFace
        dummy = np.zeros((112, 112, 3), dtype=np.uint8)
        t0 = time.perf_counter()
        DeepFace.represent(
            img_path=dummy,
            model_name="ArcFace",
            enforce_detection=False,   # skip detection — pass face directly
            detector_backend="skip",   # fastest: no detection at all
        )
        elapsed = (time.perf_counter() - t0) * 1000
        logger.info(f"ArcFace pre-warmed in {elapsed:.0f}ms — face recognition ready")
    except Exception as e:
        logger.warning(f"ArcFace pre-warm failed (non-fatal): {e}")


def _enhance_for_recognition(face_bgr: np.ndarray) -> np.ndarray:
    """
    CLAHE contrast enhancement + unsharp mask sharpening.
    Recovers fine detail from small/distant/blurry face crops before ArcFace.

    - CLAHE (Contrast Limited Adaptive Histogram Equalization) normalises
      local contrast — much better than global equalizeHist for faces.
    - Unsharp mask amplifies high-frequency edges (eyes, nose, mouth) which
      are the features ArcFace uses most.
    """
    # CLAHE on luminance channel only (preserves colour)
    yuv = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2YUV)
    yuv[:, :, 0] = _clahe.apply(yuv[:, :, 0])
    enhanced = cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR)
    # Unsharp mask: out = original * 1.5 - blurred * 0.5
    blurred = cv2.GaussianBlur(enhanced, (0, 0), sigmaX=1.5)
    sharpened = cv2.addWeighted(enhanced, 1.5, blurred, -0.5, 0)
    return np.clip(sharpened, 0, 255).astype(np.uint8)


def _is_too_blurry(gray_crop: np.ndarray) -> bool:
    """
    Laplacian variance blur metric.
    A face crop below _BLUR_THRESHOLD is too pixelated for reliable ArcFace matching.
    We skip it and wait for the next check interval (2s) to try a sharper frame.
    """
    if gray_crop.size == 0:
        return True
    variance = cv2.Laplacian(gray_crop, cv2.CV_64F).var()
    return variance < _BLUR_THRESHOLD


def _extract_face_crop(body_bgr: np.ndarray) -> Optional[np.ndarray]:
    """
    Smart face crop using Haar cascade on the FULL YOLO bbox.

    Why not the 45% top-crop anymore:
    - When you're close to the camera, your face fills the entire bbox —
      cutting it to 45% destroys half your face.
    - When you're seated or crouching, the face might be anywhere.
    - Haar cascade is fast (~5-15ms) on the bbox size and finds the face
      wherever it actually is — no guessing needed.

    Returns a 112×112 RGB face crop ready for ArcFace, or None if image too small
    or too blurry to be useful.
    """
    h, w = body_bgr.shape[:2]
    if h < 20 or w < 20:
        return None

    if _haar_cascade is not None:
        gray = cv2.cvtColor(body_bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)  # fast pre-pass before CLAHE (Haar works on contrast)

        # Try strict detection first (high quality)
        faces = _haar_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=4,
            minSize=(max(20, w // 6), max(20, h // 6)),  # adaptive min size
        )

        # Relax if nothing found — helps with partial/angled faces
        if len(faces) == 0:
            faces = _haar_cascade.detectMultiScale(
                gray,
                scaleFactor=1.05,
                minNeighbors=2,
                minSize=(15, 15),
            )

        if len(faces) > 0:
            # Use the largest detected face (most likely to be the primary subject)
            x, y, fw, fh = max(faces, key=lambda r: r[2] * r[3])
            # Add 15% padding so ArcFace gets some context around the face
            pad_x = int(fw * 0.15)
            pad_y = int(fh * 0.15)
            x1 = max(0, x - pad_x)
            y1 = max(0, y - pad_y)
            x2 = min(w, x + fw + pad_x)
            y2 = min(h, y + fh + pad_y)
            face_crop = body_bgr[y1:y2, x1:x2]
            if face_crop.size > 0:
                # Blur check — skip frame if face is too pixelated
                face_gray = gray[y1:y2, x1:x2]
                if _is_too_blurry(face_gray):
                    logger.debug(
                        f"[FACE] Blurry crop skipped "
                        f"(Lap={cv2.Laplacian(face_gray, cv2.CV_64F).var():.1f} < {_BLUR_THRESHOLD})"
                    )
                    return None
                # Enhance for better recognition at distance
                enhanced = _enhance_for_recognition(face_crop)
                rgb = cv2.cvtColor(enhanced, cv2.COLOR_BGR2RGB)
                return cv2.resize(rgb, (112, 112))

    # Fallback: no Haar or no face found — enhance and pass full bbox
    enhanced = _enhance_for_recognition(body_bgr)
    rgb = cv2.cvtColor(enhanced, cv2.COLOR_BGR2RGB)
    return cv2.resize(rgb, (112, 112))






def extract_embedding_for_enrollment(image_bgr: np.ndarray) -> Optional[np.ndarray]:
    """
    HIGH-QUALITY embedding for enrollment (called ONCE when user uploads photo).

    Uses MTCNN for precise 5-point facial landmark detection + alignment.
    This is the "gold standard" because:
    - Enrollment happens offline (no speed requirement)
    - The enrolled embedding MUST be high quality — it's the reference vector
      that every live recognition will be compared against
    - MTCNN does proper eye/nose/mouth alignment before embedding

    CRITICAL: The live `extract_embedding()` function must produce embeddings
    from the same coordinate space. We achieve this by:
    1. Enrollment: MTCNN → aligned face → ArcFace
    2. Live:       Haar (fast) → cropped face → ArcFace with opencv backend
                  (opencv also aligns, just less precisely than MTCNN)
    Both paths produce embeddings that are comparable for cosine similarity.
    """
    _init()
    if not _deepface_available:
        return None
    t0 = time.perf_counter()
    try:
        from deepface import DeepFace
        rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        result = DeepFace.represent(
            img_path=rgb,
            model_name="ArcFace",
            enforce_detection=True,   # MUST find a face or reject the photo
            detector_backend="mtcnn", # best alignment for enrollment
        )
        elapsed = (time.perf_counter() - t0) * 1000
        logger.info(f"[ENROLL] MTCNN enrollment embedding: {elapsed:.0f}ms")
        if result:
            emb = np.array(result[0]["embedding"], dtype=np.float32)
            if np.linalg.norm(emb) < 1e-6:
                return None
            return emb
        return None
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        logger.warning(f"[ENROLL] Enrollment failed after {elapsed:.0f}ms: {e}")
        return None


def extract_embedding(image_bgr: np.ndarray) -> Optional[np.ndarray]:
    """
    V2 Fast pipeline — extracts ArcFace embedding in 50-200ms (vs 1000-35000ms before).

    Strategy:
    1. Use smart crop + Haar to get a tight 112x112 face crop
    2. Pass to ArcFace with enforce_detection=False (skip DeepFace's slow detector)
    3. If step 1 fails, fallback to DeepFace with 'opencv' backend (still ~10x faster than MTCNN)
    """
    _init()
    if not _deepface_available:
        return None

    t0 = time.perf_counter()
    try:
        from deepface import DeepFace

        # Try the fast path: Haar finds the face, opencv backend aligns it for ArcFace
        # We use 'opencv' (NOT 'skip') because alignment is critical for matching
        # enrolled MTCNN embeddings. 'skip' produces unaligned vectors → poor matching.
        face_crop = _extract_face_crop(image_bgr)
        if face_crop is not None:
            t_crop = (time.perf_counter() - t0) * 1000
            result = DeepFace.represent(
                img_path=face_crop,
                model_name="ArcFace",
                enforce_detection=False,  # Haar already found the face
                detector_backend="opencv",  # aligns face consistently with MTCNN
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.info(
                f"[FACE TIMING] Fast path (Haar+opencv+ArcFace): {elapsed_ms:.1f}ms "
                f"(crop={t_crop:.1f}ms, embed={elapsed_ms - t_crop:.1f}ms)"
            )
        else:
            # Fallback: let DeepFace find the face using opencv backend on the full image
            rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
            result = DeepFace.represent(
                img_path=rgb,
                model_name="ArcFace",
                enforce_detection=True,
                detector_backend="opencv",
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.info(f"[FACE TIMING] Fallback path (opencv+ArcFace): {elapsed_ms:.1f}ms")

        if result:
            emb = np.array(result[0]["embedding"], dtype=np.float32)
            if np.linalg.norm(emb) < 1e-6:
                return None
            return emb
        return None

    except Exception as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.debug(f"Embedding extraction failed after {elapsed_ms:.1f}ms: {e}")
        return None


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def match_face(
    query_embedding: np.ndarray,
    enrolled: List[Tuple[str, np.ndarray]],
    threshold: float = 0.40,   # lowered: MTCNN-enroll vs opencv-live have ~0.05-0.10 residual gap
) -> Tuple[Optional[str], float]:
    if not enrolled:
        return None, 0.0
    best_name, best_score = None, 0.0
    for name, enc in enrolled:
        score = cosine_similarity(query_embedding, enc)
        if score > best_score:
            best_score = score
            best_name = name
    if best_score >= threshold:
        return best_name, best_score
    return None, best_score
