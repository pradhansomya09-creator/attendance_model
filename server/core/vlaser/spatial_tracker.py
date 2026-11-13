"""V-LASER Spatial Tracking, Zone Membership, Line Crossing & Hysteresis Engine.

Tracks person movement in normalized [0.0, 1.0] coordinate space across virtual grids,
classroom zones, and entry/exit lines without relying on face recognition identity.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import ulid

from .geometry import (
    Point2D,
    clamp_normalized,
    is_valid_normalized_point,
    point_in_polygon,
    point_line_side,
    point_segment_distance,
    segments_intersect,
)
from .grid_manager import (
    LineDirection,
    LineType,
    VLaserCameraConfigModel,
    VirtualLineConfig,
    VirtualZoneConfig,
    ZoneType,
)

logger = logging.getLogger(__name__)


class SpatialEventType(str, Enum):
    ENTRY = "entry"
    EXIT = "exit"
    ZONE_TRANSITION = "zone_transition"
    RESTRICTED_VIOLATION = "restricted_violation"
    LINE_CROSSING = "line_crossing"


@dataclass
class SpatialEvent:
    id: str
    camera_id: str
    track_id: int
    event_type: SpatialEventType
    line_id: Optional[str] = None
    line_name: Optional[str] = None
    line_type: Optional[LineType] = None
    from_zone_id: Optional[str] = None
    from_zone_name: Optional[str] = None
    to_zone_id: Optional[str] = None
    to_zone_name: Optional[str] = None
    direction: Optional[str] = None  # "forward", "backward", "inbound", "outbound"
    anchor: Optional[Dict[str, float]] = None
    confidence: float = 1.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "camera_id": self.camera_id,
            "track_id": self.track_id,
            "event_type": self.event_type.value,
            "line_id": self.line_id,
            "line_name": self.line_name,
            "line_type": self.line_type.value if self.line_type else None,
            "from_zone_id": self.from_zone_id,
            "from_zone_name": self.from_zone_name,
            "to_zone_id": self.to_zone_id,
            "to_zone_name": self.to_zone_name,
            "direction": self.direction,
            "anchor": self.anchor,
            "confidence": round(self.confidence, 3),
            "timestamp": round(self.timestamp, 3),
        }


@dataclass
class TrackSpatialRecord:
    """Historical spatial tracking state for a single track ID."""

    track_id: int
    last_anchor: Point2D
    last_seen_at: float
    current_zone_id: Optional[str] = None
    current_zone_name: Optional[str] = None
    candidate_zone_id: Optional[str] = None
    candidate_zone_frames: int = 0
    frames_in_zone: int = 1
    total_frames_tracked: int = 1
    line_sides: Dict[str, float] = field(default_factory=dict)
    last_crossing_time: Dict[str, float] = field(default_factory=dict)
    trail: List[Point2D] = field(default_factory=list)


def compute_bottom_center_anchor(
    bbox: Any, frame_width: int, frame_height: int
) -> Point2D:
    """Calculate the bottom-center reference anchor point of a person bounding box.
    
    Anchor Point: (x + width/2, y + height) normalized to [0.0, 1.0].
    """
    if not bbox or frame_width <= 0 or frame_height <= 0:
        return Point2D(0.5, 0.5)

    if isinstance(bbox, dict):
        x = float(bbox.get("x", 0.0))
        y = float(bbox.get("y", 0.0))
        w = float(bbox.get("width", 0.0))
        h = float(bbox.get("height", 0.0))
    elif isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        x = float(bbox[0])
        y = float(bbox[1])
        w = float(bbox[2])
        h = float(bbox[3])
    else:
        return Point2D(0.5, 0.5)

    bottom_center_x = x + (w / 2.0)
    bottom_center_y = y + h

    norm_x = clamp_normalized(bottom_center_x / float(frame_width))
    norm_y = clamp_normalized(bottom_center_y / float(frame_height))
    return Point2D(norm_x, norm_y)


class SpatialTracker:
    """Evaluates spatial positions, zone residence, and line crossing events across frames."""

    ZONE_HYSTERESIS_FRAMES = 2       # Must stay in candidate zone >= 2 frames to transition
    MIN_CROSSING_INTERVAL_SEC = 1.0   # Prevent bounce/jitter crossings within 1.0s
    MAX_TRACK_AGE_SECONDS = 5.0      # Evict lost tracks after 5.0s

    def __init__(self, camera_id: str):
        self.camera_id = camera_id
        self._tracks: Dict[int, TrackSpatialRecord] = {}
        self._recent_events: List[SpatialEvent] = []
        self._max_events_retained = 200

    def clear(self) -> None:
        self._tracks.clear()
        self._recent_events.clear()

    def get_recent_events(self, limit: int = 50) -> List[SpatialEvent]:
        return self._recent_events[-limit:]

    def _determine_zone(
        self, anchor: Point2D, zones: List[VirtualZoneConfig]
    ) -> Tuple[Optional[str], Optional[str]]:
        """Determine which configured virtual zone contains the given anchor point.
        
        Prioritizes specific zone types (restricted, entrance, teaching) over generic/custom.
        """
        candidate_zones = []
        for zone in zones:
            if not zone.enabled:
                continue
            poly_points = [v.to_point() for v in zone.polygon]
            if point_in_polygon(anchor, poly_points):
                candidate_zones.append(zone)

        if not candidate_zones:
            return None, None

        # Sort priority: restricted_area > classroom_entrance > front_teaching > student_seating > teacher_area > custom
        priority_map = {
            ZoneType.RESTRICTED_AREA: 10,
            ZoneType.CLASSROOM_ENTRANCE: 8,
            ZoneType.FRONT_TEACHING: 6,
            ZoneType.TEACHER_AREA: 5,
            ZoneType.STUDENT_SEATING: 4,
            ZoneType.CUSTOM: 2,
        }
        candidate_zones.sort(
            key=lambda z: priority_map.get(z.zone_type, 1), reverse=True
        )
        winner = candidate_zones[0]
        return winner.id, winner.name

    def update(
        self,
        tracked_faces_or_persons: List[Dict[str, Any]],
        config: VLaserCameraConfigModel,
        frame_width: int,
        frame_height: int,
        timestamp: Optional[float] = None,
    ) -> Tuple[List[Dict[str, Any]], List[SpatialEvent], Dict[str, int]]:
        """Process a frame's tracked subjects, update spatial states, and emit events.
        
        Returns:
            - spatial_subjects: enriched list of tracked subjects with anchor & zone info.
            - new_events: list of spatial events triggered in this frame.
            - zone_headcounts: count of persons in each active zone.
        """
        now = timestamp if timestamp is not None else time.time()
        new_events: List[SpatialEvent] = []
        spatial_subjects: List[Dict[str, Any]] = []
        observed_track_ids = set()

        zones = config.zones
        lines = config.lines

        for item in tracked_faces_or_persons:
            track_id = item.get("track_id", -1)
            if track_id is None or track_id < 0:
                continue

            observed_track_ids.add(track_id)
            bbox = item.get("bbox") or {}
            anchor = compute_bottom_center_anchor(bbox, frame_width, frame_height)

            zone_id, zone_name = self._determine_zone(anchor, zones)

            # Retrieve or initialize spatial state record
            record = self._tracks.get(track_id)
            if record is None:
                record = TrackSpatialRecord(
                    track_id=track_id,
                    last_anchor=anchor,
                    last_seen_at=now,
                    current_zone_id=zone_id,
                    current_zone_name=zone_name,
                    trail=[anchor],
                )
                self._tracks[track_id] = record

                # If first seen in a restricted area, emit immediate violation alert
                if zone_id:
                    matched_zone = next((z for z in zones if z.id == zone_id), None)
                    if matched_zone and matched_zone.zone_type == ZoneType.RESTRICTED_AREA:
                        event = SpatialEvent(
                            id=ulid.ulid(),
                            camera_id=self.camera_id,
                            track_id=track_id,
                            event_type=SpatialEventType.RESTRICTED_VIOLATION,
                            to_zone_id=zone_id,
                            to_zone_name=zone_name,
                            anchor=anchor.to_dict(),
                            timestamp=now,
                        )
                        new_events.append(event)
            else:
                prev_anchor = record.last_anchor
                record.last_anchor = anchor
                record.last_seen_at = now
                record.total_frames_tracked += 1
                record.trail.append(anchor)
                if len(record.trail) > 25:
                    record.trail.pop(0)

                # -----------------------------------------------------------
                # 1. Line Crossing Evaluation
                # -----------------------------------------------------------
                for line in lines:
                    if not line.enabled:
                        continue

                    lp1 = line.p1.to_point()
                    lp2 = line.p2.to_point()

                    side_prev = record.line_sides.get(line.id)
                    side_curr = point_line_side(anchor, lp1, lp2)
                    record.line_sides[line.id] = side_curr

                    # Check intersection or sign change
                    crossed = False
                    if side_prev is not None and (side_prev * side_curr < -1e-6):
                        crossed = True
                    elif segments_intersect(prev_anchor, anchor, lp1, lp2):
                        crossed = True

                    if crossed:
                        # Debounce check: prevent duplicate crossing events within cooldown
                        last_cross = record.last_crossing_time.get(line.id, 0.0)
                        if (now - last_cross) >= self.MIN_CROSSING_INTERVAL_SEC:
                            record.last_crossing_time[line.id] = now

                            # Determine direction relative to line orientation
                            direction_str = "forward" if side_curr > 0 else "backward"

                            # Event classification
                            if line.line_type == LineType.ENTRY:
                                ev_type = SpatialEventType.ENTRY
                            elif line.line_type == LineType.EXIT:
                                ev_type = SpatialEventType.EXIT
                            elif line.line_type == LineType.RESTRICTED:
                                ev_type = SpatialEventType.RESTRICTED_VIOLATION
                            else:
                                ev_type = SpatialEventType.LINE_CROSSING

                            event = SpatialEvent(
                                id=ulid.ulid(),
                                camera_id=self.camera_id,
                                track_id=track_id,
                                event_type=ev_type,
                                line_id=line.id,
                                line_name=line.name,
                                line_type=line.line_type,
                                direction=direction_str,
                                anchor=anchor.to_dict(),
                                timestamp=now,
                            )
                            new_events.append(event)

                # -----------------------------------------------------------
                # 2. Zone Transition & Hysteresis Evaluation
                # -----------------------------------------------------------
                if zone_id != record.current_zone_id:
                    if zone_id == record.candidate_zone_id:
                        record.candidate_zone_frames += 1
                        if record.candidate_zone_frames >= self.ZONE_HYSTERESIS_FRAMES:
                            old_zone_id = record.current_zone_id
                            old_zone_name = record.current_zone_name

                            record.current_zone_id = zone_id
                            record.current_zone_name = zone_name
                            record.frames_in_zone = 1
                            record.candidate_zone_id = None
                            record.candidate_zone_frames = 0

                            # Emit Zone Transition Event
                            ev_type = SpatialEventType.ZONE_TRANSITION
                            matched_zone = next((z for z in zones if z.id == zone_id), None)
                            if matched_zone and matched_zone.zone_type == ZoneType.RESTRICTED_AREA:
                                ev_type = SpatialEventType.RESTRICTED_VIOLATION

                            event = SpatialEvent(
                                id=ulid.ulid(),
                                camera_id=self.camera_id,
                                track_id=track_id,
                                event_type=ev_type,
                                from_zone_id=old_zone_id,
                                from_zone_name=old_zone_name,
                                to_zone_id=zone_id,
                                to_zone_name=zone_name,
                                anchor=anchor.to_dict(),
                                timestamp=now,
                            )
                            new_events.append(event)
                    else:
                        record.candidate_zone_id = zone_id
                        record.candidate_zone_frames = 1
                else:
                    record.frames_in_zone += 1
                    record.candidate_zone_id = None
                    record.candidate_zone_frames = 0

            # Attach spatial tracking metadata to the subject
            subject_meta = {
                **item,
                "spatial": {
                    "track_id": track_id,
                    "anchor": anchor.to_dict(),
                    "trail": [p.to_dict() for p in record.trail],
                    "current_zone_id": record.current_zone_id,
                    "current_zone_name": record.current_zone_name,
                    "frames_in_zone": record.frames_in_zone,
                    "total_frames": record.total_frames_tracked,
                },
            }
            spatial_subjects.append(subject_meta)

        # -------------------------------------------------------------------
        # 3. Clean up stale tracks older than MAX_TRACK_AGE_SECONDS
        # -------------------------------------------------------------------
        stale_track_ids = [
            tid
            for tid, rec in self._tracks.items()
            if (now - rec.last_seen_at) > self.MAX_TRACK_AGE_SECONDS
        ]
        for tid in stale_track_ids:
            self._tracks.pop(tid, None)

        # -------------------------------------------------------------------
        # 4. Compute Zone Headcounts
        # -------------------------------------------------------------------
        zone_headcounts: Dict[str, int] = {z.id: 0 for z in zones if z.enabled}
        zone_headcounts["unassigned"] = 0

        for rec in self._tracks.values():
            # Only count recently active tracks (seen within last 1.5s)
            if (now - rec.last_seen_at) <= 1.5:
                if rec.current_zone_id and rec.current_zone_id in zone_headcounts:
                    zone_headcounts[rec.current_zone_id] += 1
                else:
                    zone_headcounts["unassigned"] += 1

        # Cache new events
        if new_events:
            self._recent_events.extend(new_events)
            if len(self._recent_events) > self._max_events_retained:
                self._recent_events = self._recent_events[-self._max_events_retained :]

        return spatial_subjects, new_events, zone_headcounts

