import cv2
import base64
import logging
import httpx
import numpy as np
from typing import Optional

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://localhost:11434/api/generate"

def describe_activity_locally(frame: np.ndarray, model_name: str = "moondream") -> Optional[str]:
    """
    Sends a frame to a local Ollama vision model (like Moondream or Llava)
    running locally on the user's Mini-PC to get a chronological summary of actions.
    """
    if frame is None or frame.size == 0:
        return None

    try:
        # Check if Ollama is running first
        try:
            with httpx.Client(timeout=2.0) as client:
                resp = client.get("http://localhost:11434/")
                if resp.status_code != 200:
                    return None
        except Exception:
            # Ollama not running locally, skip vision checks gracefully
            return None

        # Encode frame to base64 JPEG
        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        b64_img = base64.b64encode(buffer).decode('utf-8')

        # Concise prompt focusing on physical activity
        prompt = (
            "Describe in one or two short sentences what the person in the image is doing. "
            "Focus on physical actions (e.g. standing, sitting, walking, opening something, cooking)."
        )

        payload = {
            "model": model_name,
            "prompt": prompt,
            "images": [b64_img],
            "stream": False
        }

        with httpx.Client(timeout=30.0) as client:
            resp = client.post(OLLAMA_URL, json=payload)
            if resp.status_code == 200:
                result = resp.json()
                summary = result.get("response", "").strip()
                logger.info(f"[OLLAMA VISION] Event action description: {summary}")
                return summary
            else:
                logger.warning(f"Ollama Vision API returned error status: {resp.status_code}")
                return None

    except Exception as e:
        logger.debug(f"Ollama Vision action summarization failed: {e}")
        return None
