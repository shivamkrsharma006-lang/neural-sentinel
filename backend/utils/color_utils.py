"""
Color extraction utilities — dominant color detection via lightweight k-means.

Uses a numpy-only k-means implementation (no sklearn dependency) to cluster
pixels in HSV space, then classifies each cluster center into one of ~16
perceptually meaningful named colors using HSV thresholds.

Pipeline:
  1. Crop bounding-box region from the frame
  2. Resize to 32×32 thumbnail for speed
  3. Convert BGR → HSV
  4. Run k-means (k=5) on the HSV pixel array
  5. Map each cluster center to the nearest named color
  6. Return top-N color names sorted by cluster size (largest first)
"""
import numpy as np
import cv2
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HSV color palette — ~16 named colors
# ---------------------------------------------------------------------------
# OpenCV HSV ranges: H ∈ [0, 179], S ∈ [0, 255], V ∈ [0, 255]

# Hue boundaries for chromatic colors (when S and V are high enough).
# Each entry: (name, h_low, h_high)
_HUE_RANGES = [
    ("red",    0,   8),
    ("orange", 8,  22),
    ("yellow", 22, 33),
    ("green",  33, 78),
    ("teal",   78, 90),
    ("cyan",   90, 100),
    ("blue",   100, 125),
    ("navy",   125, 135),
    ("purple", 135, 155),
    ("pink",   155, 170),
    ("red",    170, 180),   # red wraps around in HSV
]

# S/V thresholds for achromatic and low-saturation detection
_BLACK_V_MAX = 40
_WHITE_S_MAX = 30
_WHITE_V_MIN = 200
_GRAY_S_MAX = 40
_GRAY_V_MIN = 40
_GRAY_V_MAX = 200

# Brown / beige / maroon are mid-saturation, warm-hue variants
_BROWN_H_RANGE = (8, 25)
_BROWN_S_RANGE = (40, 180)
_BROWN_V_RANGE = (40, 140)

_BEIGE_H_RANGE = (15, 33)
_BEIGE_S_RANGE = (20, 80)
_BEIGE_V_RANGE = (170, 255)

_MAROON_H_RANGE = (0, 10)
_MAROON_S_RANGE = (80, 255)
_MAROON_V_RANGE = (40, 120)


def _classify_hsv(h: float, s: float, v: float) -> str:
    """Classify a single HSV pixel into a named color string.

    Priority order: achromatic checks first (black → white → gray),
    then special mid-saturation colors (brown, beige, maroon),
    then pure chromatic hue mapping.

    Args:
        h: Hue in [0, 179].
        s: Saturation in [0, 255].
        v: Value in [0, 255].

    Returns:
        Named color string, e.g. ``"red"``, ``"black"``.
    """
    # --- achromatic ---
    if v < _BLACK_V_MAX:
        return "black"
    if s < _WHITE_S_MAX and v > _WHITE_V_MIN:
        return "white"
    if s < _GRAY_S_MAX and _GRAY_V_MIN <= v <= _GRAY_V_MAX:
        return "gray"

    # --- mid-saturation specials ---
    if (_MAROON_H_RANGE[0] <= h <= _MAROON_H_RANGE[1]
            and _MAROON_S_RANGE[0] <= s <= _MAROON_S_RANGE[1]
            and _MAROON_V_RANGE[0] <= v <= _MAROON_V_RANGE[1]):
        return "maroon"

    if (_BROWN_H_RANGE[0] <= h <= _BROWN_H_RANGE[1]
            and _BROWN_S_RANGE[0] <= s <= _BROWN_S_RANGE[1]
            and _BROWN_V_RANGE[0] <= v <= _BROWN_V_RANGE[1]):
        return "brown"

    if (_BEIGE_H_RANGE[0] <= h <= _BEIGE_H_RANGE[1]
            and _BEIGE_S_RANGE[0] <= s <= _BEIGE_S_RANGE[1]
            and _BEIGE_V_RANGE[0] <= v <= _BEIGE_V_RANGE[1]):
        return "beige"

    # --- chromatic hue lookup ---
    for name, h_lo, h_hi in _HUE_RANGES:
        if h_lo <= h < h_hi:
            return name

    return "gray"  # fallback


def _kmeans_numpy(
    pixels: np.ndarray,
    k: int = 5,
    max_iter: int = 10,
    seed: int = 42,
) -> tuple:
    """Lightweight k-means clustering using only numpy.

    Args:
        pixels: ``(N, 3)`` float32 array of HSV values.
        k: Number of clusters.
        max_iter: Maximum number of Lloyd iterations.
        seed: Random seed for reproducible centroid initialisation.

    Returns:
        Tuple of ``(centers, labels, counts)`` where:
        - centers: ``(k, 3)`` cluster centroids.
        - labels:  ``(N,)`` cluster assignment per pixel.
        - counts:  ``(k,)`` number of pixels in each cluster.
    """
    rng = np.random.RandomState(seed)
    n = pixels.shape[0]
    k = min(k, n)  # can't have more clusters than pixels

    # Forgy initialisation: pick k random data points
    indices = rng.choice(n, size=k, replace=False)
    centers = pixels[indices].copy()

    labels = np.zeros(n, dtype=np.int32)

    for _ in range(max_iter):
        # Assignment step — squared Euclidean distances
        # Shape: (N, k)
        dists = np.linalg.norm(
            pixels[:, np.newaxis, :] - centers[np.newaxis, :, :], axis=2
        )
        new_labels = np.argmin(dists, axis=1).astype(np.int32)

        # Convergence check
        if np.array_equal(new_labels, labels):
            break
        labels = new_labels

        # Update step
        for j in range(k):
            mask = labels == j
            if mask.any():
                centers[j] = pixels[mask].mean(axis=0)

    counts = np.bincount(labels, minlength=k)
    return centers, labels, counts


def extract_dominant_colors(
    frame: np.ndarray,
    bbox: list,
    n_colors: int = 2,
) -> List[str]:
    """Extract the dominant named colors from a bounding-box crop.

    Args:
        frame: Full BGR image (H×W×3 uint8).
        bbox: Bounding box as ``[x1, y1, x2, y2]`` in pixel coords.
        n_colors: Number of top colors to return.

    Returns:
        List of up to *n_colors* named color strings sorted by
        cluster size (largest first).  Returns ``[]`` on invalid input.
    """
    try:
        x1, y1, x2, y2 = map(int, bbox[:4])
    except (TypeError, ValueError):
        logger.debug("Invalid bbox format: %s", bbox)
        return []

    # Clamp to frame bounds
    h, w = frame.shape[:2]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)

    if x2 <= x1 or y2 <= y1:
        logger.debug("Empty crop region after clamping: [%d,%d,%d,%d]", x1, y1, x2, y2)
        return []

    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return []

    # Resize to 32×32 for speed
    thumb = cv2.resize(crop, (32, 32), interpolation=cv2.INTER_AREA)

    # Convert BGR → HSV
    hsv = cv2.cvtColor(thumb, cv2.COLOR_BGR2HSV)
    pixels = hsv.reshape(-1, 3).astype(np.float32)

    # Run k-means (k=5)
    centers, _labels, counts = _kmeans_numpy(pixels, k=5)

    # Sort clusters by size (descending)
    order = np.argsort(-counts)

    # Classify each center and deduplicate while preserving rank order
    seen: set = set()
    result: List[str] = []
    for idx in order:
        h_val, s_val, v_val = centers[idx]
        name = _classify_hsv(h_val, s_val, v_val)
        if name not in seen:
            seen.add(name)
            result.append(name)
        if len(result) >= n_colors:
            break

    return result


def get_clothing_colors(
    frame: np.ndarray,
    bbox: list,
) -> Dict[str, List[str]]:
    """Estimate upper-body and lower-body clothing colors.

    Splits the bounding box into an upper half (torso / shirt) and a
    lower half (legs / trousers) and extracts dominant colors from each.

    Args:
        frame: Full BGR image (H×W×3 uint8).
        bbox: Bounding box as ``[x1, y1, x2, y2]`` in pixel coords.

    Returns:
        Dict with ``"upper"`` and ``"lower"`` keys, each mapping to a
        list of named color strings.  Returns empty lists on failure.
    """
    empty: Dict[str, List[str]] = {"upper": [], "lower": []}

    try:
        x1, y1, x2, y2 = map(int, bbox[:4])
    except (TypeError, ValueError):
        return empty

    y_mid = (y1 + y2) // 2

    upper_bbox = [x1, y1, x2, y_mid]
    lower_bbox = [x1, y_mid, x2, y2]

    return {
        "upper": extract_dominant_colors(frame, upper_bbox),
        "lower": extract_dominant_colors(frame, lower_bbox),
    }
