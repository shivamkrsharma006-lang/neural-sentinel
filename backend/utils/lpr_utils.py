import cv2
import numpy as np
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

_reader = None

def _init_reader():
    global _reader
    if _reader is not None:
        return
    try:
        import easyocr
        # Initialize easyocr reader for English (plates are alphanumeric)
        # Set gpu=False to enforce stable CPU execution matching our thread budget
        _reader = easyocr.Reader(['en'], gpu=False)
        logger.info("Local EasyOCR reader initialized successfully for LPR")
    except Exception as e:
        logger.error(f"Failed to initialize EasyOCR reader: {e}")

def read_license_plate(vehicle_crop: np.ndarray) -> Optional[str]:
    """
    Processes a vehicle image crop, runs local OCR, and extracts any alphanumeric plate characters.
    Uses adaptive filtering to enhance plate contrast.
    """
    if vehicle_crop is None or vehicle_crop.size == 0:
        return None

    _init_reader()
    if _reader is None:
        return None

    try:
        # Preprocessing: convert to grayscale
        gray = cv2.cvtColor(vehicle_crop, cv2.COLOR_BGR2GRAY)
        
        # Scale up if crop is too small (makes text readable for OCR)
        h, w = gray.shape
        if w < 200:
            scale = 200.0 / w
            gray = cv2.resize(gray, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            
        # Bilateral filter preserves sharp edges while smoothing background noise
        gray = cv2.bilateralFilter(gray, 11, 17, 17)
        
        # Otsu thresholding converts image to high-contrast binary
        thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
        
        # Run EasyOCR
        results = _reader.readtext(gray)
        if not results:
            results = _reader.readtext(thresh)
            
        if not results:
            return None
            
        candidates = []
        for bbox, text, score in results:
            # Clean: uppercase, remove non-alphanumeric symbols
            cleaned = re.sub(r'[^A-Z0-9]', '', text.upper())
            # License plates usually range between 4 and 10 characters
            if 4 <= len(cleaned) <= 12:
                candidates.append((cleaned, score))
                
        if not candidates:
            return None
            
        # Sort by confidence score descending
        candidates.sort(key=lambda x: x[1], reverse=True)
        best_plate = candidates[0][0]
        
        logger.info(f"[LPR] Extracted plate text: '{best_plate}' (conf={candidates[0][1]:.3f})")
        return best_plate
        
    except Exception as e:
        logger.debug(f"Local LPR extraction failed: {e}")
        return None
