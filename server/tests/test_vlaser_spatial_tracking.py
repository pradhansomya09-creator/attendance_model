"""Tests for V-LASER Person Bottom-Center Anchoring & Spatial Tracking Engine."""

from __future__ import annotations

import time
import pytest
from core.vlaser.geometry import Point2D
from core.vlaser.grid_manager import (
    LineDirection,
    LineType,
    NormalizedPointModel,
    VLaserCameraConfigModel,
    VirtualLineConfig,
    VirtualZoneConfig,
    ZoneType,
)
from core.vlaser.spatial_tracker import (
    SpatialEventType,
    SpatialTracker,
    compute_bottom_center_anchor,
)


def _make_test_vlaser_config(camera_id: str = "cam-test-spatial") -> VLaserCameraConfigModel:
    return VLaserCameraConfigModel(
        camera_id=camera_id,
        classroom="LH-Spatial",
        grid_enabled=True,
        grid_rows=10,
        grid_cols=10,
        lines=[
            VirtualLineConfig(
                id="line-entry-gate",
                name="Front Entry Line",
                line_type=LineType.ENTRY,
                direction=LineDirection.FORWARD,
                p1=NormalizedPointModel(x=0.0, y=0.5),
                p2=NormalizedPointModel(x=1.0, y=0.5),
                color="#10b981",
                enabled=True,
            ),
            VirtualLineConfig(
                id="line-exit-gate",
                name="Back Exit Line",
                line_type=LineType.EXIT,
                direction=LineDirection.FORWARD,
                p1=NormalizedPointModel(x=0.0, y=0.9),
                p2=NormalizedPointModel(x=1.0, y=0.9),
                color="#f97316",
                enabled=True,
            ),
        ],
        zones=[
            VirtualZoneConfig(
                id="zone-entrance",
                name="Entrance Lobby",
                zone_type=ZoneType.CLASSROOM_ENTRANCE,
                polygon=[
                    NormalizedPointModel(x=0.0, y=0.0),
                    NormalizedPointModel(x=1.0, y=0.0),
                    NormalizedPointModel(x=1.0, y=0.4),
                    NormalizedPointModel(x=0.0, y=0.4),
                ],
                color="#38bdf8",
                opacity=0.25,
                enabled=True,
            ),
            VirtualZoneConfig(
                id="zone-seating",
                name="Seating Area",
                zone_type=ZoneType.STUDENT_SEATING,
                polygon=[
                    NormalizedPointModel(x=0.0, y=0.45),
                    NormalizedPointModel(x=1.0, y=0.45),
                    NormalizedPointModel(x=1.0, y=0.85),
                    NormalizedPointModel(x=0.0, y=0.85),
                ],
                color="#22c55e",
                opacity=0.20,
                enabled=True,
            ),
            VirtualZoneConfig(
                id="zone-restricted",
                name="Server Cabinet",
                zone_type=ZoneType.RESTRICTED_AREA,
                polygon=[
                    NormalizedPointModel(x=0.8, y=0.86),
                    NormalizedPointModel(x=1.0, y=0.86),
                    NormalizedPointModel(x=1.0, y=1.0),
                    NormalizedPointModel(x=0.8, y=1.0),
                ],
                color="#ef4444",
                opacity=0.3,
                enabled=True,
            ),
        ],
        is_active=True,
    )


def test_bottom_center_anchor_computation():
    # Bounding box in 640x360 frame: x=100, y=50, w=80, h=100
    # Center X = 100 + 40 = 140 -> 140 / 640 = 0.2188
    # Bottom Y = 50 + 100 = 150 -> 150 / 360 = 0.4167
    bbox = {"x": 100, "y": 50, "width": 80, "height": 100}
    anchor = compute_bottom_center_anchor(bbox, frame_width=640, frame_height=360)

    assert anchor.x == pytest.approx(140 / 640.0, abs=1e-3)
    assert anchor.y == pytest.approx(150 / 360.0, abs=1e-3)
    assert 0.0 <= anchor.x <= 1.0
    assert 0.0 <= anchor.y <= 1.0


def test_spatial_tracker_zone_residence_and_transition():
    config = _make_test_vlaser_config()
    tracker = SpatialTracker("cam-test-spatial")

    t0 = 1000.0

    # Frame 1: Person 101 starts inside Entrance Lobby (y=0.2)
    person_f1 = [{"track_id": 101, "bbox": {"x": 280, "y": 30, "width": 80, "height": 40}}]  # anchor y=(30+40)/360=0.194
    subjects, events, headcounts = tracker.update(
        person_f1, config, frame_width=640, frame_height=360, timestamp=t0
    )

    assert len(subjects) == 1
    assert subjects[0]["spatial"]["current_zone_id"] == "zone-entrance"
    assert subjects[0]["spatial"]["current_zone_name"] == "Entrance Lobby"
    assert headcounts["zone-entrance"] == 1
    assert len(events) == 0

    # Frame 2: Person 101 moves towards Seating Area (y=0.6)
    # Hysteresis requires 2 consecutive frames in new zone
    person_f2 = [{"track_id": 101, "bbox": {"x": 280, "y": 170, "width": 80, "height": 50}}]  # anchor y=(170+50)/360=0.611
    subjects2, events2, headcounts2 = tracker.update(
        person_f2, config, frame_width=640, frame_height=360, timestamp=t0 + 0.1
    )

    # Note: Moving across y=0.5 also crosses the Entry Line!
    assert any(e.event_type == SpatialEventType.ENTRY for e in events2)
    # Zone has not officially transitioned yet due to 2-frame hysteresis
    assert subjects2[0]["spatial"]["current_zone_id"] == "zone-entrance"

    # Frame 3: Person 101 remains in Seating Area for second frame
    person_f3 = [{"track_id": 101, "bbox": {"x": 280, "y": 175, "width": 80, "height": 50}}]
    subjects3, events3, headcounts3 = tracker.update(
        person_f3, config, frame_width=640, frame_height=360, timestamp=t0 + 0.2
    )

    # Confirmed zone transition event emitted
    assert any(
        e.event_type == SpatialEventType.ZONE_TRANSITION and e.to_zone_id == "zone-seating"
        for e in events3
    )
    assert subjects3[0]["spatial"]["current_zone_id"] == "zone-seating"
    assert headcounts3["zone-seating"] == 1


def test_line_crossing_jitter_debouncing():
    config = _make_test_vlaser_config()
    tracker = SpatialTracker("cam-test-spatial")

    t0 = 2000.0

    # Start above line y=0.5 (anchor y = 0.4)
    p_above = [{"track_id": 201, "bbox": {"x": 300, "y": 100, "width": 40, "height": 44}}]  # anchor y=144/360=0.40
    tracker.update(p_above, config, 640, 360, timestamp=t0)

    # Cross below line y=0.5 (anchor y = 0.6) -> Crossing 1
    p_below = [{"track_id": 201, "bbox": {"x": 300, "y": 170, "width": 40, "height": 46}}]  # anchor y=216/360=0.60
    _, events1, _ = tracker.update(p_below, config, 640, 360, timestamp=t0 + 0.1)
    entry_events = [e for e in events1 if e.event_type == SpatialEventType.ENTRY]
    assert len(entry_events) == 1

    # Immediate jitter back across line 0.2s later (within 1.0s cooldown)
    p_jitter_above = [{"track_id": 201, "bbox": {"x": 300, "y": 100, "width": 40, "height": 44}}]
    _, events_jitter, _ = tracker.update(p_jitter_above, config, 640, 360, timestamp=t0 + 0.3)
    # Debounced: should NOT emit duplicate crossing within 1.0 second cooldown
    assert len(events_jitter) == 0

    # Cross again after 1.5s -> crossing succeeds
    p_cross_later = [{"track_id": 201, "bbox": {"x": 300, "y": 170, "width": 40, "height": 46}}]
    _, events_later, _ = tracker.update(p_cross_later, config, 640, 360, timestamp=t0 + 1.6)
    assert any(e.event_type == SpatialEventType.ENTRY for e in events_later)


def test_track_eviction_after_timeout():
    config = _make_test_vlaser_config()
    tracker = SpatialTracker("cam-test-spatial")

    t0 = 3000.0
    p = [{"track_id": 301, "bbox": {"x": 300, "y": 100, "width": 40, "height": 40}}]
    tracker.update(p, config, 640, 360, timestamp=t0)
    assert 301 in tracker._tracks

    # Empty frame 6 seconds later -> track 301 must be pruned
    tracker.update([], config, 640, 360, timestamp=t0 + 6.0)
    assert 301 not in tracker._tracks

