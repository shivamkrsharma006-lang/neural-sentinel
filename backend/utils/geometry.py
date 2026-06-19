import numpy as np
from typing import List, Tuple, Optional


Point = Tuple[float, float]


def point_in_polygon(point: Point, polygon: List[Point]) -> bool:
    """Ray casting algorithm for point-in-polygon test."""
    if len(polygon) < 3:
        return False
    x, y = point
    n = len(polygon)
    inside = False
    px, py = polygon[-1]
    for cx, cy in polygon:
        if ((cy > y) != (py > y)) and (x < (px - cx) * (y - cy) / (py - cy + 1e-9) + cx):
            inside = not inside
        px, py = cx, cy
    return inside


def cross_product_sign(o: Point, a: Point, b: Point) -> float:
    """Returns the sign of the cross product of vectors OA and OB."""
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def segments_intersect(p1: Point, p2: Point, p3: Point, p4: Point) -> bool:
    """Check if segment p1-p2 intersects segment p3-p4."""
    d1 = cross_product_sign(p3, p4, p1)
    d2 = cross_product_sign(p3, p4, p2)
    d3 = cross_product_sign(p1, p2, p3)
    d4 = cross_product_sign(p1, p2, p4)
    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
       ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True
    return False


def detect_line_crossing(
    prev_pos: Point,
    curr_pos: Point,
    line_start: Point,
    line_end: Point,
) -> Optional[str]:
    """
    Returns crossing direction: 'forward', 'backward', or None.
    Forward = left-to-right relative to the line's normal.
    """
    if not segments_intersect(prev_pos, curr_pos, line_start, line_end):
        return None
    # Compute which side the object moved from/to
    lx = line_end[0] - line_start[0]
    ly = line_end[1] - line_start[1]
    # Normal vector (perpendicular, pointing "right")
    nx, ny = ly, -lx
    # Movement vector
    mx = curr_pos[0] - prev_pos[0]
    my = curr_pos[1] - prev_pos[1]
    dot = mx * nx + my * ny
    return "forward" if dot > 0 else "backward"


def compute_centroid(bbox: Tuple[float, float, float, float]) -> Point:
    """Returns (cx, cy) from (x1, y1, x2, y2) bbox."""
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2, (y1 + y2) / 2)


def compute_bottom_center(bbox: Tuple[float, float, float, float]) -> Point:
    """Returns bottom-center of bbox — better for zone entry."""
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2, y2)


def pixel_distance(p1: Point, p2: Point) -> float:
    return float(np.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2))


def normalize_points(points: List[dict], frame_w: int, frame_h: int) -> List[Point]:
    """Convert normalized [0,1] coords to pixel coords."""
    return [(p["x"] * frame_w, p["y"] * frame_h) for p in points]


def is_armed(config: dict) -> bool:
    """Check if zone is within its arming schedule."""
    schedule = config.get("arming_schedule")
    if not schedule or not schedule.get("enabled"):
        return True
    from datetime import datetime
    now = datetime.now()
    day_name = now.strftime("%A").lower()
    allowed_days = [d.lower() for d in schedule.get("days", [])]
    if allowed_days and day_name not in allowed_days:
        return False
    start_str = schedule.get("start_time", "00:00")
    end_str = schedule.get("end_time", "23:59")
    try:
        start_h, start_m = map(int, start_str.split(":"))
        end_h, end_m = map(int, end_str.split(":"))
        now_minutes = now.hour * 60 + now.minute
        start_minutes = start_h * 60 + start_m
        end_minutes = end_h * 60 + end_m
        return start_minutes <= now_minutes <= end_minutes
    except Exception:
        return True
