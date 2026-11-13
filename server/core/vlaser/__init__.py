"""V-LASER Virtual Grid and Spatial Tracking Core Module."""

from .geometry import (
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
from .grid_manager import (
    DEFAULT_LINE_COLORS,
    DEFAULT_ZONE_COLORS,
    LineDirection,
    LineType,
    NormalizedPointModel,
    VLaserCameraConfigModel,
    VirtualLineConfig,
    VirtualZoneConfig,
    ZoneType,
    generate_default_vlaser_config,
)
from .spatial_tracker import (
    SpatialEvent,
    SpatialEventType,
    SpatialTracker,
    TrackSpatialRecord,
    compute_bottom_center_anchor,
)
from .identity_association import (
    IdentityState,
    TrackIdentityBinding,
    VLaserIdentityAssociationManager,
)

__all__ = [
    "Point2D",
    "clamp_normalized",
    "compute_polygon_area",
    "cross_product",
    "is_polygon_self_intersecting",
    "is_valid_normalized_point",
    "point_in_polygon",
    "point_line_side",
    "point_segment_distance",
    "segments_intersect",
    "DEFAULT_LINE_COLORS",
    "DEFAULT_ZONE_COLORS",
    "LineDirection",
    "LineType",
    "NormalizedPointModel",
    "VLaserCameraConfigModel",
    "VirtualLineConfig",
    "VirtualZoneConfig",
    "ZoneType",
    "generate_default_vlaser_config",
    "SpatialEvent",
    "SpatialEventType",
    "SpatialTracker",
    "TrackSpatialRecord",
    "compute_bottom_center_anchor",
    "IdentityState",
    "TrackIdentityBinding",
    "VLaserIdentityAssociationManager",
]
