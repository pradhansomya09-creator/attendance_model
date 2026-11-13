"""V-LASER Virtual Grid, Line, and Zone Management Models & Validation."""

from __future__ import annotations

import json
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator

from .geometry import (
    Point2D,
    compute_polygon_area,
    is_polygon_self_intersecting,
    is_valid_normalized_point,
)


class LineType(str, Enum):
    ENTRY = "entry"
    EXIT = "exit"
    INTERNAL = "internal"
    RESTRICTED = "restricted"


class LineDirection(str, Enum):
    BIDIRECTIONAL = "bidirectional"
    FORWARD = "forward"
    BACKWARD = "backward"


class ZoneType(str, Enum):
    CLASSROOM_ENTRANCE = "classroom_entrance"
    STUDENT_SEATING = "student_seating"
    TEACHER_AREA = "teacher_area"
    FRONT_TEACHING = "front_teaching"
    RESTRICTED_AREA = "restricted_area"
    CUSTOM = "custom"


DEFAULT_ZONE_COLORS = {
    ZoneType.CLASSROOM_ENTRANCE: "#38bdf8",  # Sky blue
    ZoneType.STUDENT_SEATING: "#22c55e",     # Green
    ZoneType.TEACHER_AREA: "#a855f7",        # Purple
    ZoneType.FRONT_TEACHING: "#eab308",      # Amber
    ZoneType.RESTRICTED_AREA: "#ef4444",     # Red
    ZoneType.CUSTOM: "#06b6d4",              # Cyan
}

DEFAULT_LINE_COLORS = {
    LineType.ENTRY: "#10b981",       # Emerald
    LineType.EXIT: "#f97316",        # Orange
    LineType.INTERNAL: "#3b82f6",    # Blue
    LineType.RESTRICTED: "#ef4444",  # Red
}


class NormalizedPointModel(BaseModel):
    x: float = Field(..., ge=0.0, le=1.0)
    y: float = Field(..., ge=0.0, le=1.0)

    def to_point(self) -> Point2D:
        return Point2D(x=self.x, y=self.y)


class VirtualLineConfig(BaseModel):
    id: str
    name: str = Field(..., min_length=1, max_length=64)
    line_type: LineType = LineType.INTERNAL
    direction: LineDirection = LineDirection.BIDIRECTIONAL
    p1: NormalizedPointModel
    p2: NormalizedPointModel
    color: Optional[str] = None
    enabled: bool = True

    @field_validator("p2")
    @classmethod
    def validate_non_zero_length(cls, v: NormalizedPointModel, info) -> NormalizedPointModel:
        p1 = info.data.get("p1")
        if p1 is not None and abs(p1.x - v.x) < 1e-4 and abs(p1.y - v.y) < 1e-4:
            raise ValueError("Line start (p1) and end (p2) points cannot be identical.")
        return v


class VirtualZoneConfig(BaseModel):
    id: str
    name: str = Field(..., min_length=1, max_length=64)
    zone_type: ZoneType = ZoneType.CUSTOM
    polygon: List[NormalizedPointModel] = Field(..., min_length=3)
    color: Optional[str] = None
    opacity: float = Field(0.25, ge=0.05, le=1.0)
    enabled: bool = True

    @field_validator("polygon")
    @classmethod
    def validate_polygon_geometry(
        cls, vertices: List[NormalizedPointModel]
    ) -> List[NormalizedPointModel]:
        points = [v.to_point() for v in vertices]
        if len(points) < 3:
            raise ValueError("A zone polygon must contain at least 3 vertices.")
        area = abs(compute_polygon_area(points))
        if area <= 1e-6:
            raise ValueError("Polygon has zero or near-zero area (collinear vertices).")
        if is_polygon_self_intersecting(points):
            raise ValueError("Polygon is self-intersecting (complex polygons are not allowed).")
        return vertices


class VLaserCameraConfigModel(BaseModel):
    camera_id: str
    classroom: Optional[str] = None
    grid_enabled: bool = True
    grid_rows: int = Field(10, ge=2, le=50)
    grid_cols: int = Field(10, ge=2, le=50)
    grid_color: str = Field("#00f3ff", pattern=r"^#(?:[0-9a-fA-F]{3}){1,2}$")
    grid_opacity: float = Field(0.25, ge=0.0, le=1.0)
    lines: List[VirtualLineConfig] = Field(default_factory=list)
    zones: List[VirtualZoneConfig] = Field(default_factory=list)
    is_active: bool = True

    def serialize_lines_json(self) -> str:
        return json.dumps([l.model_dump() for l in self.lines])

    def serialize_zones_json(self) -> str:
        return json.dumps([z.model_dump() for z in self.zones])


def generate_default_vlaser_config(camera_id: str, classroom: Optional[str] = None) -> VLaserCameraConfigModel:
    """Generate sensible default virtual grid, entry/exit lines, and zones for a classroom camera."""
    return VLaserCameraConfigModel(
        camera_id=camera_id,
        classroom=classroom or "Main Classroom",
        grid_enabled=True,
        grid_rows=10,
        grid_cols=10,
        grid_color="#00f3ff",
        grid_opacity=0.25,
        lines=[
            VirtualLineConfig(
                id=f"{camera_id}-line-entry",
                name="Main Entrance Line",
                line_type=LineType.ENTRY,
                direction=LineDirection.FORWARD,
                p1=NormalizedPointModel(x=0.05, y=0.85),
                p2=NormalizedPointModel(x=0.40, y=0.85),
                color="#10b981",
                enabled=True,
            ),
            VirtualLineConfig(
                id=f"{camera_id}-line-exit",
                name="Classroom Exit Line",
                line_type=LineType.EXIT,
                direction=LineDirection.FORWARD,
                p1=NormalizedPointModel(x=0.45, y=0.85),
                p2=NormalizedPointModel(x=0.80, y=0.85),
                color="#f97316",
                enabled=True,
            ),
        ],
        zones=[
            VirtualZoneConfig(
                id=f"{camera_id}-zone-entrance",
                name="Classroom Entrance",
                zone_type=ZoneType.CLASSROOM_ENTRANCE,
                polygon=[
                    NormalizedPointModel(x=0.02, y=0.70),
                    NormalizedPointModel(x=0.45, y=0.70),
                    NormalizedPointModel(x=0.45, y=0.98),
                    NormalizedPointModel(x=0.02, y=0.98),
                ],
                color="#38bdf8",
                opacity=0.25,
                enabled=True,
            ),
            VirtualZoneConfig(
                id=f"{camera_id}-zone-seating",
                name="Student Seating Area",
                zone_type=ZoneType.STUDENT_SEATING,
                polygon=[
                    NormalizedPointModel(x=0.05, y=0.20),
                    NormalizedPointModel(x=0.95, y=0.20),
                    NormalizedPointModel(x=0.95, y=0.68),
                    NormalizedPointModel(x=0.05, y=0.68),
                ],
                color="#22c55e",
                opacity=0.20,
                enabled=True,
            ),
            VirtualZoneConfig(
                id=f"{camera_id}-zone-teaching",
                name="Front Teaching Area",
                zone_type=ZoneType.FRONT_TEACHING,
                polygon=[
                    NormalizedPointModel(x=0.20, y=0.02),
                    NormalizedPointModel(x=0.80, y=0.02),
                    NormalizedPointModel(x=0.80, y=0.18),
                    NormalizedPointModel(x=0.20, y=0.18),
                ],
                color="#eab308",
                opacity=0.25,
                enabled=True,
            ),
        ],
        is_active=True,
    )

