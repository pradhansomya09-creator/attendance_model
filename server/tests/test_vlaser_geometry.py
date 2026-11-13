"""Tests for V-LASER 2D Vector Geometry and Polygon Validation."""

import pytest
from core.vlaser.geometry import (
    Point2D,
    clamp_normalized,
    compute_polygon_area,
    cross_product,
    is_polygon_self_intersecting,
    is_valid_normalized_point,
    point_in_polygon,
    point_line_side,
    point_segment_distance,
    segments_intersect,
)


def test_normalized_point_validation():
    p_valid = Point2D(0.5, 0.75)
    assert is_valid_normalized_point(p_valid) is True
    assert clamp_normalized(1.5) == 1.0
    assert clamp_normalized(-0.2) == 0.0

    p_out = Point2D(1.2, 0.5)
    assert is_valid_normalized_point(p_out) is False


def test_segment_intersection():
    # Perpendicular crossing
    p1 = Point2D(0.2, 0.5)
    p2 = Point2D(0.8, 0.5)
    p3 = Point2D(0.5, 0.2)
    p4 = Point2D(0.5, 0.8)
    assert segments_intersect(p1, p2, p3, p4) is True

    # Parallel non-intersecting
    q1 = Point2D(0.2, 0.2)
    q2 = Point2D(0.8, 0.2)
    q3 = Point2D(0.2, 0.6)
    q4 = Point2D(0.8, 0.6)
    assert segments_intersect(q1, q2, q3, q4) is False


def test_point_in_polygon_ray_casting():
    # Unit box from (0.2, 0.2) to (0.8, 0.8)
    box = [
        Point2D(0.2, 0.2),
        Point2D(0.8, 0.2),
        Point2D(0.8, 0.8),
        Point2D(0.2, 0.8),
    ]

    inside_pt = Point2D(0.5, 0.5)
    outside_pt = Point2D(0.1, 0.5)
    on_boundary_pt = Point2D(0.5, 0.2)

    assert point_in_polygon(inside_pt, box) is True
    assert point_in_polygon(outside_pt, box) is False
    assert point_in_polygon(on_boundary_pt, box) is True


def test_polygon_area_shoelace():
    # Square with side 0.5 -> area 0.25
    square = [
        Point2D(0.1, 0.1),
        Point2D(0.6, 0.1),
        Point2D(0.6, 0.6),
        Point2D(0.1, 0.6),
    ]
    assert abs(compute_polygon_area(square)) == pytest.approx(0.25, abs=1e-5)


def test_polygon_self_intersection_detection():
    # Valid convex square
    convex = [
        Point2D(0.1, 0.1),
        Point2D(0.5, 0.1),
        Point2D(0.5, 0.5),
        Point2D(0.1, 0.5),
    ]
    assert is_polygon_self_intersecting(convex) is False

    # Bowtie self-intersecting polygon: vertices cross in the middle
    bowtie = [
        Point2D(0.1, 0.1),
        Point2D(0.5, 0.5),
        Point2D(0.5, 0.1),
        Point2D(0.1, 0.5),
    ]
    assert is_polygon_self_intersecting(bowtie) is True


def test_point_line_side_and_distance():
    p1 = Point2D(0.0, 0.5)
    p2 = Point2D(1.0, 0.5)

    # Point above line (p1 -> p2 is left-to-right, so y > 0.5 is left/positive in screen coordinates or right depending on y-down)
    pt_above = Point2D(0.5, 0.2)
    pt_below = Point2D(0.5, 0.8)

    side_above = point_line_side(pt_above, p1, p2)
    side_below = point_line_side(pt_below, p1, p2)

    # Must have opposite signs
    assert (side_above * side_below) < 0

    # Distance to horizontal line y=0.5
    assert point_segment_distance(Point2D(0.5, 0.8), p1, p2) == pytest.approx(0.3, abs=1e-5)

