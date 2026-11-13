"""V-LASER Persistence and Configuration Service."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import ulid
from sqlalchemy import select

from core.vlaser.grid_manager import (
    LineType,
    VLaserCameraConfigModel,
    VirtualLineConfig,
    VirtualZoneConfig,
    generate_default_vlaser_config,
)
from core.vlaser.spatial_tracker import SpatialEvent, SpatialEventType, SpatialTracker
from core.vlaser.identity_association import VLaserIdentityAssociationManager
from database.models import CctvCamera, VLaserCameraConfig
import database.session as db_session

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class VLaserService:
    """Manages V-LASER camera grid, line, and zone persistence & caching."""

    _cache: Dict[str, VLaserCameraConfigModel] = {}
    _spatial_trackers: Dict[str, SpatialTracker] = {}
    _identity_managers: Dict[str, VLaserIdentityAssociationManager] = {}

    @classmethod
    def get_spatial_tracker(cls, camera_id: str) -> SpatialTracker:
        if camera_id not in cls._spatial_trackers:
            cls._spatial_trackers[camera_id] = SpatialTracker(camera_id)
        return cls._spatial_trackers[camera_id]

    @classmethod
    def get_all_recent_events(cls, limit: int = 50) -> List[SpatialEvent]:
        """Aggregate recent events across all active camera spatial trackers."""
        all_events: List[SpatialEvent] = []
        for tracker in cls._spatial_trackers.values():
            all_events.extend(tracker.get_recent_events(limit=limit))
        all_events.sort(key=lambda e: e.timestamp, reverse=True)
        return all_events[:limit]

    @classmethod
    def get_identity_manager(cls, camera_id: str) -> VLaserIdentityAssociationManager:
        if camera_id not in cls._identity_managers:
            cls._identity_managers[camera_id] = VLaserIdentityAssociationManager(camera_id)
        return cls._identity_managers[camera_id]

    @classmethod
    def get_cached_config(cls, camera_id: str) -> Optional[VLaserCameraConfigModel]:
        return cls._cache.get(camera_id)

    @classmethod
    def invalidate_cache(cls, camera_id: str) -> None:
        cls._cache.pop(camera_id, None)
        if camera_id in cls._spatial_trackers:
            cls._spatial_trackers[camera_id].clear()
        if camera_id in cls._identity_managers:
            cls._identity_managers[camera_id].clear()

    @classmethod
    async def process_spatial_frame(
        cls,
        camera_id: str,
        tracked_objects: list[dict],
        frame_width: int,
        frame_height: int,
        timestamp: Optional[float] = None,
        session=None,
        organization_id: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], List[SpatialEvent], Dict[str, int]]:
        """Evaluate spatial tracking across zones and lines for a given frame."""
        config = cls.get_cached_config(camera_id)
        if config is None:
            if session is not None:
                config = await cls.get_config(session, camera_id, organization_id=organization_id)
            else:
                async with db_session.AsyncSessionLocal() as s:
                    config = await cls.get_config(s, camera_id, organization_id=organization_id)

        tracker = cls.get_spatial_tracker(camera_id)
        active_tracks, spatial_events, zone_counts = tracker.update(
            tracked_objects,
            config,
            frame_width=frame_width,
            frame_height=frame_height,
            timestamp=timestamp,
        )

        # Update identity manager spatial events & zone residence
        identity_mgr = cls.get_identity_manager(camera_id)
        lines_by_id = {line.id: line for line in config.lines}
        zones_by_id = {zone.id: zone for zone in config.zones}

        for ev in spatial_events:
            if ev.event_type == SpatialEventType.LINE_CROSSING and ev.line_id:
                line_cfg = lines_by_id.get(ev.line_id)
                if line_cfg and line_cfg.line_type == LineType.ENTRY:
                    identity_mgr.record_spatial_entry(ev.track_id, timestamp=ev.timestamp)

        for track_item in active_tracks:
            tid = track_item.get("track_id")
            zone_id = track_item.get("current_zone_id")
            if tid is not None and zone_id:
                zone_cfg = zones_by_id.get(zone_id)
                zone_type_val = zone_cfg.zone_type.value if zone_cfg else None
                identity_mgr.update_zone_residence(tid, zone_type_val, delta_seconds=0.1)

        identity_mgr.prune_stale_tracks(max_age_seconds=10.0, now=timestamp)
        return active_tracks, spatial_events, zone_counts

    @classmethod
    async def get_config(
        cls,
        session,
        camera_id: str,
        organization_id: Optional[str] = None,
    ) -> VLaserCameraConfigModel:
        """Fetch saved V-LASER config or generate a standard template for the camera."""
        stmt = select(VLaserCameraConfig).where(
            VLaserCameraConfig.camera_id == camera_id
        )
        if organization_id is not None:
            stmt = stmt.where(VLaserCameraConfig.organization_id == organization_id)
        else:
            stmt = stmt.where(VLaserCameraConfig.organization_id.is_(None))

        res = await session.execute(stmt)
        record = res.scalar_one_or_none()

        if record is not None:
            try:
                raw_lines = json.loads(record.lines_json or "[]")
                raw_zones = json.loads(record.zones_json or "[]")
                lines = [VirtualLineConfig(**l) for l in raw_lines]
                zones = [VirtualZoneConfig(**z) for z in raw_zones]
            except Exception as parse_err:
                logger.warning(
                    "[VLaserService] Error parsing lines/zones for camera %s: %s",
                    camera_id,
                    parse_err,
                )
                lines, zones = [], []

            model = VLaserCameraConfigModel(
                camera_id=record.camera_id,
                classroom=record.classroom,
                grid_enabled=bool(record.grid_enabled),
                grid_rows=int(record.grid_rows),
                grid_cols=int(record.grid_cols),
                grid_color=record.grid_color,
                grid_opacity=float(record.grid_opacity),
                lines=lines,
                zones=zones,
                is_active=bool(record.is_active),
            )
            cls._cache[camera_id] = model
            return model

        # Camera classroom lookup for default template
        cam_res = await session.execute(
            select(CctvCamera).where(CctvCamera.id == camera_id)
        )
        cam = cam_res.scalar_one_or_none()
        classroom = cam.classroom if cam else None

        default_cfg = generate_default_vlaser_config(camera_id, classroom)
        cls._cache[camera_id] = default_cfg
        return default_cfg

    @classmethod
    async def save_config(
        cls,
        session,
        config: VLaserCameraConfigModel,
        organization_id: Optional[str] = None,
    ) -> VLaserCameraConfigModel:
        """Persist V-LASER camera grid, line, and zone configuration."""
        stmt = select(VLaserCameraConfig).where(
            VLaserCameraConfig.camera_id == config.camera_id
        )
        if organization_id is not None:
            stmt = stmt.where(VLaserCameraConfig.organization_id == organization_id)
        else:
            stmt = stmt.where(VLaserCameraConfig.organization_id.is_(None))

        res = await session.execute(stmt)
        record = res.scalar_one_or_none()
        now = _utc_now()

        lines_json = config.serialize_lines_json()
        zones_json = config.serialize_zones_json()

        if record is None:
            record = VLaserCameraConfig(
                id=ulid.ulid(),
                camera_id=config.camera_id,
                classroom=config.classroom,
                grid_enabled=config.grid_enabled,
                grid_rows=config.grid_rows,
                grid_cols=config.grid_cols,
                grid_color=config.grid_color,
                grid_opacity=config.grid_opacity,
                lines_json=lines_json,
                zones_json=zones_json,
                is_active=config.is_active,
                created_at=now,
                updated_at=now,
                organization_id=organization_id,
            )
            session.add(record)
        else:
            record.classroom = config.classroom
            record.grid_enabled = config.grid_enabled
            record.grid_rows = config.grid_rows
            record.grid_cols = config.grid_cols
            record.grid_color = config.grid_color
            record.grid_opacity = config.grid_opacity
            record.lines_json = lines_json
            record.zones_json = zones_json
            record.is_active = config.is_active
            record.updated_at = now

        await session.commit()
        cls._cache[config.camera_id] = config
        return config

    @classmethod
    async def delete_config(
        cls,
        session,
        camera_id: str,
        organization_id: Optional[str] = None,
    ) -> bool:
        """Delete stored configuration and reset to defaults."""
        stmt = select(VLaserCameraConfig).where(
            VLaserCameraConfig.camera_id == camera_id
        )
        if organization_id is not None:
            stmt = stmt.where(VLaserCameraConfig.organization_id == organization_id)
        else:
            stmt = stmt.where(VLaserCameraConfig.organization_id.is_(None))

        res = await session.execute(stmt)
        record = res.scalar_one_or_none()
        if record is not None:
            await session.delete(record)
            await session.commit()
            cls.invalidate_cache(camera_id)
            return True
        cls.invalidate_cache(camera_id)
        return False

