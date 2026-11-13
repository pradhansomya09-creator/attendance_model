"""V-LASER Geometry & Spatial Computation Engine.

Provides resolution-independent 2D vector geometry, normalized coordinate validation,
Ray-Casting point-in-polygon tests, segment intersection tests, and polygon self-intersection validation.
"""

from __future__ import annotations

import math
from typing import List, NamedTuple, Optional, Tuple


class Point2D(NamedTuple):
    x: float
    y: float

    @classmethod
    def from_dict(cls, data: dict) -> Point2D:
        return cls(x=float(data.get("x", 0.0)), y=float(data.get("y", 0.0)))

    def to_dict(self) -> dict:
        return {"x": round(self.x, 4), "y": round(self.y, 4)}


def clamp_normalized(val: float) -> float:
    """Clamp float to normalized range [0.0, 1.0]."""
    return max(0.0, min(1.0, float(val)))


def is_valid_normalized_point(p: Point2D, tolerance: float = 1e-4) -> bool:
    """Verify coordinate lies within [0.0 - tol, 1.0 + tol]."""
    return (
        (-tolerance <= p.x <= 1.0 + tolerance)
        and (-tolerance <= p.y <= 1.0 + tolerance)
    )


def cross_product(p1: Point2D, p2: Point2D, p3: Point2D) -> float:
    """Compute 2D cross product of vector (p1 -> p2) and vector (p1 -> p3).
    
    Positive: p3 is to the left of directed line p1 -> p2.
    Negative: p3 is to the right.
    Zero: collinear.
    """
    return (p2.x - p1.x) * (p3.y - p1.y) - (p2.y - p1.y) * (p3.x - p1.x)


def point_line_side(point: Point2D, line_p1: Point2D, line_p2: Point2D) -> float:
    """Determine which side of a directed line a point lies on."""
    return cross_product(line_p1, line_p2, point)


def _on_segment(p: Point2D, q: Point2D, r: Point2D) -> bool:
    """Given collinear points p, q, r, check if q lies on segment pr."""
    return (
        min(p.x, r.x) - 1e-7 <= q.x <= max(p.x, r.x) + 1e-7
        and min(p.y, r.y) - 1e-7 <= q.y <= max(p.y, r.y) + 1e-7
    )


def segments_intersect(
    p1: Point2D,
    p2: Point2D,
    p3: Point2D,
    p4: Point2D,
    *,
    touch_is_intersection: bool = True,
) -> bool:
    """Check if line segment p1-p2 intersects line segment p3-p4."""
    d1 = cross_product(p3, p4, p1)
    d2 = cross_product(p3, p4, p2)
    d3 = cross_product(p1, p2, p3)
    d4 = cross_product(p1, p2, p4)

    # General case: straddle each other
    if ((d1 > 1e-7 and d2 < -1e-7) or (d1 < -1e-7 and d2 > 1e-7)) and (
        (d3 > 1e-7 and d4 < -1e-7) or (d3 < -1e-7 and d4 > 1e-7)
    ):
        return True

    if not touch_is_intersection:
        return False

    # Special collinear / endpoint cases
    if abs(d1) <= 1e-7 and _on_segment(p3, p1, p4):
        return True
    if abs(d2) <= 1e-7 and _on_segment(p3, p2, p4):
        return True
    if abs(d3) <= 1e-7 and _on_segment(p1, p3, p2):
        return True
    if abs(d4) <= 1e-7 and _on_segment(p1, p4, p2):
        return True

    return False


def point_in_polygon(point: Point2D, polygon: List[Point2D]) -> bool:
    """Ray casting algorithm to determine if point lies inside polygon.
    
    Includes points that lie directly on polygon boundaries.
    """
    n = len(polygon)
    if n < 3:
        return False

    inside = False
    for i in range(n):
        j = (i + 1) % n
        p_i = polygon[i]
        p_j = polygon[j]

        # Check if point lies exactly on this segment
        cp = cross_product(p_i, p_j, point)
        if abs(cp) <= 1e-6 and _on_segment(p_i, point, p_j):
            return True

        # Ray-casting crossing test
        if ((p_i.y > point.y) != (p_j.y > point.y)) and (
            point.x < (p_j.x - p_i.x) * (point.y - p_i.y) / (p_j.y - p_i.y + 1e-12) + p_i.x
        ):
            inside = not inside

    return inside


def compute_polygon_area(polygon: List[Point2D]) -> float:
    """Calculate the signed area of a polygon using the Shoelace formula."""
    n = len(polygon)
    if n < 3:
        return 0.0

    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += polygon[i].x * polygon[j].y
        area -= polygon[j].x * polygon[i].y
    return 0.5 * area


def is_polygon_self_intersecting(polygon: List[Point2D]) -> bool:
    """Check if any non-adjacent edges of the polygon intersect each other.
    
    A self-intersecting polygon (bowtie, figure-8) produces undefined zone membership.
    """
    n = len(polygon)
    if n < 4:
        return False

    for i in range(n):
        p1 = polygon[i]
        p2 = polygon[(i + 1) % n]

        # Test against every non-adjacent edge
        for j in range(i + 2, n):
            # The closing edge (n-1 -> 0) is adjacent to (0 -> 1), so skip
            if i == 0 and j == n - 1:
                continue

            p3 = polygon[j]
            p4 = polygon[(j + 1) % n]

            # For non-adjacent segments, touch or crossing is invalid
            if segments_intersect(p1, p2, p3, p4, touch_is_intersection=True):
                # Verify it's not just sharing identical adjacent endpoints
                if p1 == p4 or p2 == p3 or p1 == p3 or p2 == p4:
                    continue
                return True

    return False


def point_segment_distance(point: Point2D, p1: Point2D, p2: Point2D) -> float:
    """Perpendicular distance from point to segment p1-p2."""
    dx = p2.x - p1.x
    dy = p2.y - p1.y
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-12:
        return math.hypot(point.x - p1.x, point.y - p1.y)

    # Projection factor t clamped to [0, 1]
    t = max(0.0, min(1.0, ((point.x - p1.x) * dx + (point.y - p1.y) * dy) / length_sq))
    proj_x = p1.x + t * dx
    proj_y = p1.y + t * dy
    return math.hypot(point.x - proj_x, point.y - proj_y)

