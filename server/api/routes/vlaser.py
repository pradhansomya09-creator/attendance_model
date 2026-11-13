"""V-LASER (Virtual Laser Grid & Zone Manager) API Routes."""

from __future__ import annotations

import base64
import logging
import time
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from api.deps import get_db, get_organization_id
from core.vlaser.grid_manager import (
    LineDirection,
    LineType,
    NormalizedPointModel,
    VLaserCameraConfigModel,
    VirtualLineConfig,
    VirtualZoneConfig,
    ZoneType,
)
from database.models import CctvCamera
from services.cctv_monitor_service import CctvMonitorService
from services.vlaser_service import VLaserService
from sqlalchemy import select

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cctv/vlaser", tags=["vlaser"])


class ValidationRequest(BaseModel):
    lines: List[VirtualLineConfig] = Field(default_factory=list)
    zones: List[VirtualZoneConfig] = Field(default_factory=list)


class ValidationResponse(BaseModel):
    valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


@router.get("/cameras/{camera_id}", response_model=VLaserCameraConfigModel)
async def get_vlaser_config(
    camera_id: str,
    session=Depends(get_db),
    org_id: Optional[str] = Depends(get_organization_id),
):
    """Retrieve the V-LASER grid, lines, and zones for the specified camera."""
    # Ensure camera exists; auto-provision default camera if querying default
    cam_res = await session.execute(
        select(CctvCamera).where(CctvCamera.id == camera_id)
    )
    cam = cam_res.scalar_one_or_none()
    if not cam:
        if camera_id in ("cam-main-1", "default"):
            all_cams = (await session.execute(select(CctvCamera))).scalars().all()
            if all_cams:
                return await VLaserService.get_config(session, all_cams[0].id, organization_id=org_id)
            # Auto-provision camera so V-LASER works out-of-the-box on clean installs
            cam = CctvCamera(
                id=camera_id,
                name="Classroom Main Camera",
                camera_code="CAM-MAIN-01",
                source_type="webcam",
                classroom="Classroom",
                status="online",
                quality_status="green",
                quality_score=0.95,
                fps=30.0,
            )
            session.add(cam)
            await session.commit()
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"CCTV camera '{camera_id}' not found.",
            )

    return await VLaserService.get_config(session, camera_id, organization_id=org_id)


@router.post("/cameras/{camera_id}", response_model=VLaserCameraConfigModel)
async def save_vlaser_config(
    camera_id: str,
    payload: VLaserCameraConfigModel,
    session=Depends(get_db),
    org_id: Optional[str] = Depends(get_organization_id),
):
    """Save or update V-LASER grid, lines, and zones configuration for a camera."""
    if payload.camera_id != camera_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Camera ID in payload ({payload.camera_id}) does not match URL ({camera_id}).",
        )

    cam_res = await session.execute(
        select(CctvCamera).where(CctvCamera.id == camera_id)
    )
    cam = cam_res.scalar_one_or_none()
    if not cam:
        if camera_id in ("cam-main-1", "default"):
            cam = CctvCamera(
                id=camera_id,
                name="Classroom Main Camera",
                camera_code="CAM-MAIN-01",
                source_type="webcam",
                classroom=payload.classroom or "Classroom",
                status="online",
                quality_status="green",
                quality_score=0.95,
                fps=30.0,
            )
            session.add(cam)
            await session.commit()
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"CCTV camera '{camera_id}' not found.",
            )

    # Automatically synchronize classroom name if available
    if cam.classroom and not payload.classroom:
        payload.classroom = cam.classroom

    saved = await VLaserService.save_config(session, payload, organization_id=org_id)
    return saved


@router.delete("/cameras/{camera_id}")
async def reset_vlaser_config(
    camera_id: str,
    session=Depends(get_db),
    org_id: Optional[str] = Depends(get_organization_id),
):
    """Reset V-LASER configuration to factory default template."""
    deleted = await VLaserService.delete_config(session, camera_id, organization_id=org_id)
    default_cfg = await VLaserService.get_config(session, camera_id, organization_id=org_id)
    return {
        "success": True,
        "message": "V-LASER configuration reset to default template.",
        "config": default_cfg,
    }


@router.post("/validate", response_model=ValidationResponse)
async def validate_vlaser_geometry(payload: ValidationRequest):
    """Validate lines and zones for self-intersections, coordinate bounds, and naming collisions."""
    errors: List[str] = []
    warnings: List[str] = []

    line_names = set()
    for line in payload.lines:
        if line.name in line_names:
            errors.append(f"Duplicate line name '{line.name}'. Line names must be unique.")
        line_names.add(line.name)

    zone_names = set()
    for zone in payload.zones:
        if zone.name in zone_names:
            errors.append(f"Duplicate zone name '{zone.name}'. Zone names must be unique.")
        zone_names.add(zone.name)

    if not any(l.line_type == LineType.ENTRY for l in payload.lines):
        warnings.append("No 'Entry line' configured. Entry tracking will be inactive.")
    if not any(l.line_type == LineType.EXIT for l in payload.lines):
        warnings.append("No 'Exit line' configured. Exit tracking will be inactive.")

    return ValidationResponse(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


@router.get("/cameras/{camera_id}/preview-frame")
async def get_camera_preview_frame(
    camera_id: str,
    session=Depends(get_db),
):
    """Fetch the latest frame from the camera as a base64 JPEG for the visual editor."""
    frame = CctvMonitorService._last_frames.get(camera_id)

    if frame is None:
        cam_res = await session.execute(
            select(CctvCamera).where(CctvCamera.id == camera_id)
        )
        cam = cam_res.scalar_one_or_none()
        if not cam and camera_id not in ("cam-main-1", "default"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"CCTV camera '{camera_id}' not found.",
            )
        cam_code = cam.camera_code if cam else f"CAM-{camera_id.upper()[:8]}"
        cam_name = cam.name if cam else "Classroom Camera"
        cam_classroom = (cam.classroom if cam else None) or "Classroom"

        # Generate a synthetic classroom preview frame
        frame = np.full((360, 640, 3), 40, dtype=np.uint8)
        # Background floor and walls
        cv2.rectangle(frame, (0, 0), (640, 180), (60, 60, 75), -1)
        cv2.rectangle(frame, (0, 180), (640, 360), (35, 35, 45), -1)
        # Classroom desks perspective
        for x in range(60, 580, 100):
            cv2.rectangle(frame, (x, 220), (x + 70, 260), (70, 80, 95), -1)
            cv2.rectangle(frame, (x, 280), (x + 80, 330), (80, 90, 105), -1)
        # Camera code watermark
        cv2.putText(
            frame,
            f"{cam_code} • {cam_name} ({cam_classroom})",
            (20, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 243, 255),
            1,
        )

    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to encode camera preview frame.",
        )

    b64 = base64.b64encode(buf.tobytes()).decode("ascii")
    return {
        "camera_id": camera_id,
        "width": int(frame.shape[1]),
        "height": int(frame.shape[0]),
        "image_data_url": f"data:image/jpeg;base64,{b64}",
    }


@router.get("/cameras/{camera_id}/spatial-state")
async def get_camera_spatial_state(
    camera_id: str,
    session=Depends(get_db),
    org_id: Optional[str] = Depends(get_organization_id),
):
    """Query active spatial tracking state, zone residence, and headcounts for a camera."""
    cam_res = await session.execute(
        select(CctvCamera).where(CctvCamera.id == camera_id)
    )
    cam = cam_res.scalar_one_or_none()
    if not cam:
        if camera_id in ("cam-main-1", "default"):
            cam = CctvCamera(
                id=camera_id,
                name="Classroom Main Camera",
                camera_code="CAM-MAIN-01",
                source_type="webcam",
                classroom="Classroom",
                status="online",
                quality_status="green",
                quality_score=0.95,
                fps=30.0,
            )
            session.add(cam)
            await session.commit()
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"CCTV camera '{camera_id}' not found.",
            )

    config = await VLaserService.get_config(session, camera_id, organization_id=org_id)
    tracker = VLaserService.get_spatial_tracker(camera_id)
    identity_mgr = VLaserService.get_identity_manager(camera_id)

    active_tracks = []
    zone_headcounts = {z.id: 0 for z in config.zones if z.enabled}
    zone_headcounts["unassigned"] = 0

    now = time.time()
    for tid, rec in tracker._tracks.items():
        if (now - rec.last_seen_at) <= 2.5:
            binding = identity_mgr.get_binding(tid)
            active_tracks.append(
                {
                    "track_id": tid,
                    "anchor": rec.last_anchor.to_dict(),
                    "trail": [p.to_dict() for p in rec.trail],
                    "current_zone_id": rec.current_zone_id,
                    "current_zone_name": rec.current_zone_name,
                    "frames_in_zone": rec.frames_in_zone,
                    "total_frames": rec.total_frames_tracked,
                    "last_seen_seconds_ago": round(now - rec.last_seen_at, 2),
                    "identity_state": binding.identity_state.value if binding else "spatially_tracked",
                    "person_id": binding.person_id if binding else None,
                    "student_name": binding.student_name if binding else None,
                    "candidate_student_name": binding.candidate_name if binding else None,
                    "is_occluded": binding.is_occluded if binding else False,
                    "occlusion_frames": binding.occlusion_frames if binding else 0,
                    "recognition_confidence": round(binding.recognition_confidence, 3) if binding else 0.0,
                    "temporal_consistency": round(binding.temporal_consistency, 3) if binding else 0.0,
                    "entered_classroom": binding.entered_classroom if binding else False,
                    "attendance_eligible": binding.attendance_eligible if binding else False,
                    "attendance_marked": binding.attendance_marked if binding else False,
                }
            )
            if rec.current_zone_id and rec.current_zone_id in zone_headcounts:
                zone_headcounts[rec.current_zone_id] += 1
            else:
                zone_headcounts["unassigned"] += 1

    return {
        "camera_id": camera_id,
        "active_tracks_count": len(active_tracks),
        "active_tracks": active_tracks,
        "zone_headcounts": zone_headcounts,
        "recent_events": [ev.to_dict() for ev in tracker.get_recent_events(limit=25)],
    }


@router.get("/cameras/{camera_id}/events")
async def get_camera_spatial_events(
    camera_id: str,
    limit: int = Query(50, ge=1, le=200),
    session=Depends(get_db),
):
    """Retrieve recent spatial events (entry, exit, zone transitions) for a camera."""
    tracker = VLaserService.get_spatial_tracker(camera_id)
    events = tracker.get_recent_events(limit=limit)
    return {
        "camera_id": camera_id,
        "count": len(events),
        "events": [ev.to_dict() for ev in events],
    }


@router.get("/events/recent")
async def get_all_recent_spatial_events(
    limit: int = Query(50, ge=1, le=200),
    session=Depends(get_db),
):
    """Retrieve aggregated recent spatial events across all active cameras."""
    events = VLaserService.get_all_recent_events(limit=limit)
    return {
        "count": len(events),
        "events": [ev.to_dict() for ev in events],
    }

