"""Real-Time CCTV Health Monitoring, Stream Capture, Reconnection, and Recovery Service."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
import ulid
from sqlalchemy import select

from core.vision.image_quality import analyze_and_enhance_frame, compute_frame_difference
import database.session as db_session
from database.models import CctvCamera, CctvCameraLog

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class CctvMonitorService:
    """Tracks camera health, frozen frames, RTSP/video/webcam capture, and auto-reconnection."""

    _active_streams: Dict[str, asyncio.Task] = {}
    _last_frames: Dict[str, np.ndarray] = {}
    _freeze_counters: Dict[str, int] = {}
    _simulated_faults: Dict[str, str] = {}

    @classmethod
    def set_simulated_fault(cls, camera_id: str, fault: Optional[str]) -> None:
        if fault:
            cls._simulated_faults[camera_id] = fault
        else:
            cls._simulated_faults.pop(camera_id, None)

    @classmethod
    def get_simulated_fault(cls, camera_id: str) -> Optional[str]:
        return cls._simulated_faults.get(camera_id)

    @staticmethod
    async def log_camera_event(
        session,
        *,
        camera_id: str,
        error_category: str,
        severity: str,
        message: str,
        recovery_status: str = "pending",
        corrective_action: Optional[str] = None,
        organization_id: Optional[str] = None,
    ) -> CctvCameraLog:
        entry = CctvCameraLog(
            id=ulid.ulid(),
            camera_id=camera_id,
            error_category=error_category,
            severity=severity,
            message=message,
            detected_at=_utc_now(),
            recovery_status=recovery_status,
            corrective_action=corrective_action,
            organization_id=organization_id,
        )
        session.add(entry)
        return entry

    @staticmethod
    async def resolve_open_logs(
        session,
        *,
        camera_id: str,
        error_category: Optional[str] = None,
        recovery_status: str = "recovered",
        corrective_action: Optional[str] = None,
    ) -> int:
        stmt = select(CctvCameraLog).where(
            CctvCameraLog.camera_id == camera_id,
            CctvCameraLog.resolved_at.is_(None),
        )
        if error_category:
            stmt = stmt.where(CctvCameraLog.error_category == error_category)
        res = await session.execute(stmt)
        logs = res.scalars().all()
        now = _utc_now()
        for row in logs:
            row.resolved_at = now
            if row.detected_at:
                row.duration_seconds = max(
                    0.0, (now - row.detected_at).total_seconds()
                )
            row.recovery_status = recovery_status
            if corrective_action:
                row.corrective_action = corrective_action
        return len(logs)

    @classmethod
    async def find_backup_camera(
        cls, session, camera: CctvCamera
    ) -> Optional[CctvCamera]:
        """Locate an online backup camera covering the same classroom or configured backup_camera_id."""
        if camera.backup_camera_id:
            res = await session.execute(
                select(CctvCamera).where(
                    CctvCamera.id == camera.backup_camera_id,
                    CctvCamera.is_active.is_(True),
                    CctvCamera.status == "online",
                )
            )
            direct = res.scalar_one_or_none()
            if direct is not None:
                return direct

        if camera.classroom:
            res = await session.execute(
                select(CctvCamera).where(
                    CctvCamera.id != camera.id,
                    CctvCamera.classroom == camera.classroom,
                    CctvCamera.is_active.is_(True),
                    CctvCamera.status == "online",
                )
            )
            return res.scalars().first()
        return None

    @classmethod
    async def record_frame_telemetry(
        cls,
        camera_id: str,
        frame: np.ndarray,
        fps: float,
        organization_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Analyze incoming frame for freeze/quality issues and update camera DB status."""
        prev_frame = cls._last_frames.get(camera_id)
        mad = compute_frame_difference(frame, prev_frame)
        cls._last_frames[camera_id] = frame.copy()

        frozen_detected = False
        if mad is not None and mad < 0.35:
            count = cls._freeze_counters.get(camera_id, 0) + 1
            cls._freeze_counters[camera_id] = count
            if count >= 15:
                frozen_detected = True
        else:
            cls._freeze_counters[camera_id] = 0

        enhanced, quality_report = analyze_and_enhance_frame(frame)
        now = _utc_now()

        async with db_session.AsyncSessionLocal() as session:
            res = await session.execute(
                select(CctvCamera).where(CctvCamera.id == camera_id)
            )
            camera = res.scalar_one_or_none()
            if camera is not None:
                camera.last_frame_at = now
                camera.last_connected_at = now
                camera.disconnected_at = None
                camera.fps = round(float(fps), 1)
                camera.quality_status = quality_report.status
                camera.quality_score = round(float(quality_report.score), 3)

                if frozen_detected:
                    camera.status = "unstable"
                    camera.recording_status = "failed"
                    await cls.log_camera_event(
                        session,
                        camera_id=camera_id,
                        error_category="frozen_footage",
                        severity="warning",
                        message="Consecutive identical frames detected (frozen video stream).",
                        recovery_status="recovering",
                        corrective_action="Monitoring stream for motion recovery / reconnect.",
                        organization_id=organization_id,
                    )
                else:
                    camera.status = "online"
                    camera.recording_status = "recording"
                    await cls.resolve_open_logs(
                        session,
                        camera_id=camera_id,
                        recovery_status="recovered",
                        corrective_action="Live stream restored and delivering valid frames.",
                    )

                if quality_report.status == "red":
                    await cls.log_camera_event(
                        session,
                        camera_id=camera_id,
                        error_category=(
                            quality_report.issues[0]
                            if quality_report.issues
                            else "low_light"
                        ),
                        severity="warning",
                        message=(
                            "Camera image quality fell below threshold: "
                            + ", ".join(quality_report.issues or ["poor_visibility"])
                        ),
                        recovery_status="manual_fallback",
                        corrective_action=(
                            "Applied adaptive enhancement; marked attendance Pending Verification."
                        ),
                        organization_id=organization_id,
                    )
                await session.commit()

        return {
            "quality": quality_report.to_dict(),
            "frozen_detected": frozen_detected,
            "enhanced_frame": enhanced,
        }

    @classmethod
    async def handle_camera_disconnection(
        cls,
        camera_id: str,
        *,
        error_category: str = "disconnected",
        message: str = "Camera stream disconnected or unreachable.",
        organization_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Transition camera to offline/recovering, check backup cameras, and log outage."""
        now = _utc_now()
        async with db_session.AsyncSessionLocal() as session:
            res = await session.execute(
                select(CctvCamera).where(CctvCamera.id == camera_id)
            )
            camera = res.scalar_one_or_none()
            if camera is None:
                return {"found": False}

            camera.status = "offline"
            camera.recording_status = "failed"
            camera.disconnected_at = camera.disconnected_at or now
            camera.reconnect_attempts = int(camera.reconnect_attempts or 0) + 1

            backup = await cls.find_backup_camera(session, camera)
            recovery_status = "backup_used" if backup else "recovering"
            action = (
                f"Switched monitoring to backup camera {backup.camera_code} ({backup.name})."
                if backup
                else "Automatic reconnection scheduled; faculty manual fallback available."
            )

            await cls.log_camera_event(
                session,
                camera_id=camera_id,
                error_category=error_category,
                severity="critical",
                message=message,
                recovery_status=recovery_status,
                corrective_action=action,
                organization_id=organization_id or camera.organization_id,
            )
            await session.commit()

            return {
                "found": True,
                "camera_id": camera.id,
                "status": camera.status,
                "backup_camera": (
                    {
                        "id": backup.id,
                        "name": backup.name,
                        "camera_code": backup.camera_code,
                    }
                    if backup
                    else None
                ),
                "corrective_action": action,
            }

    @classmethod
    async def probe_camera_source(
        cls, camera: CctvCamera
    ) -> Dict[str, Any]:
        """Probe configured camera source (RTSP, video file, webcam index, or simulated)."""
        fault = cls.get_simulated_fault(camera.id)
        if fault == "offline":
            return {
                "connected": False,
                "status": "offline",
                "recording_status": "failed",
                "error_category": "disconnected",
                "message": "Simulated camera power/network failure.",
            }
        if fault == "recording_failed":
            return {
                "connected": True,
                "status": "recording_failed",
                "recording_status": "failed",
                "error_category": "recording_failed",
                "message": "Camera reachable but recording buffer unavailable.",
            }
        if fault == "frozen":
            synthetic = np.full((360, 640, 3), 120, dtype=np.uint8)
            cv2.putText(
                synthetic,
                "FROZEN STREAM",
                (160, 180),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (230, 230, 230),
                2,
            )
            _, report = analyze_and_enhance_frame(synthetic)
            return {
                "connected": True,
                "status": "unstable",
                "recording_status": "failed",
                "frozen": True,
                "quality": report.to_dict(),
                "error_category": "frozen_footage",
                "message": "Frozen footage detected across consecutive frames.",
            }
        if fault == "darkness":
            dark = np.random.randint(0, 14, (360, 640, 3), dtype=np.uint8)
            _, report = analyze_and_enhance_frame(dark)
            return {
                "connected": True,
                "status": "online",
                "recording_status": "recording",
                "quality": report.to_dict(),
                "message": "Low-light / darkness probe evaluated.",
            }
        if fault == "blur":
            frame = np.full((360, 640, 3), 110, dtype=np.uint8)
            blurred = cv2.GaussianBlur(frame, (31, 31), 15)
            _, report = analyze_and_enhance_frame(blurred)
            return {
                "connected": True,
                "status": "online",
                "recording_status": "recording",
                "quality": report.to_dict(),
                "message": "Severe blur / opacity probe evaluated.",
            }

        if camera.source_type == "simulated":
            # Generate a crisp synthetic classroom preview frame with healthy contrast & edges
            frame = np.full((360, 640, 3), 128, dtype=np.uint8)
            for idx in range(0, 640, 40):
                cv2.line(frame, (idx, 0), (idx, 360), (165, 175, 185), 2)
            for idx in range(0, 360, 40):
                cv2.line(frame, (0, idx), (640, idx), (150, 160, 170), 2)
            cv2.putText(
                frame,
                f"{camera.camera_code} OK",
                (140, 190),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.2,
                (245, 245, 245),
                3,
            )
            _, report = analyze_and_enhance_frame(frame)
            return {
                "connected": True,
                "status": "online",
                "recording_status": "recording",
                "quality": report.to_dict(),
                "fps": 25.0,
                "message": "Simulated CCTV stream healthy.",
            }

        # Real OpenCV VideoCapture probe for RTSP / video_file / local webcam index
        source: Any = camera.source_uri or "0"
        if camera.source_type == "webcam":
            try:
                source = int(source)
            except (TypeError, ValueError):
                source = 0

        def _capture_once() -> Dict[str, Any]:
            cap = cv2.VideoCapture(source)
            try:
                if not cap.isOpened():
                    return {
                        "connected": False,
                        "status": "offline",
                        "recording_status": "failed",
                        "error_category": "missing_stream",
                        "message": f"Unable to open camera source '{source}'.",
                    }
                ok, frame = cap.read()
                if not ok or frame is None:
                    return {
                        "connected": True,
                        "status": "recording_failed",
                        "recording_status": "failed",
                        "error_category": "recording_failed",
                        "message": "Camera opened but returned no video frame.",
                    }
                fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
                _, report = analyze_and_enhance_frame(frame)
                return {
                    "connected": True,
                    "status": "online",
                    "recording_status": "recording",
                    "fps": fps if fps > 0 else 25.0,
                    "quality": report.to_dict(),
                    "message": "Stream connected and delivering valid frames.",
                }
            finally:
                cap.release()

        return await asyncio.to_thread(_capture_once)

    @classmethod
    async def attempt_reconnect(
        cls, camera_id: str, *, clear_fault: bool = False
    ) -> Dict[str, Any]:
        """Attempt camera reconnection and update health status & logs."""
        if clear_fault:
            cls.set_simulated_fault(camera_id, None)

        async with db_session.AsyncSessionLocal() as session:
            res = await session.execute(
                select(CctvCamera).where(CctvCamera.id == camera_id)
            )
            camera = res.scalar_one_or_none()
            if camera is None:
                return {"found": False, "reconnected": False}

            camera.status = "recovering"
            camera.reconnect_attempts = int(camera.reconnect_attempts or 0) + 1
            await session.commit()

        probe = await cls.probe_camera_source(camera)
        now = _utc_now()

        async with db_session.AsyncSessionLocal() as session:
            res = await session.execute(
                select(CctvCamera).where(CctvCamera.id == camera_id)
            )
            camera = res.scalar_one_or_none()
            if camera is None:
                return {"found": False, "reconnected": False}

            if probe.get("connected") and probe.get("status") == "online":
                quality = probe.get("quality") or {}
                camera.status = "online"
                camera.recording_status = probe.get("recording_status", "recording")
                camera.quality_status = quality.get("status", "green")
                camera.quality_score = float(quality.get("score", 1.0))
                camera.fps = float(probe.get("fps", 25.0))
                camera.last_connected_at = now
                camera.last_frame_at = now
                camera.disconnected_at = None
                await cls.resolve_open_logs(
                    session,
                    camera_id=camera_id,
                    recovery_status="recovered",
                    corrective_action="Automatic reconnection succeeded.",
                )
                await session.commit()
                return {
                    "found": True,
                    "reconnected": True,
                    "status": camera.status,
                    "quality_status": camera.quality_status,
                    "probe": probe,
                }

            camera.status = probe.get("status", "offline")
            camera.recording_status = probe.get("recording_status", "failed")
            camera.disconnected_at = camera.disconnected_at or now
            backup = await cls.find_backup_camera(session, camera)
            await cls.log_camera_event(
                session,
                camera_id=camera_id,
                error_category=probe.get("error_category", "disconnected"),
                severity="critical",
                message=probe.get("message", "Reconnection attempt failed."),
                recovery_status="backup_used" if backup else "failed",
                corrective_action=(
                    f"Backup camera {backup.camera_code} available."
                    if backup
                    else "Reconnection failed; manual attendance fallback required."
                ),
                organization_id=camera.organization_id,
            )
            await session.commit()
            return {
                "found": True,
                "reconnected": False,
                "status": camera.status,
                "backup_camera": (
                    {"id": backup.id, "camera_code": backup.camera_code}
                    if backup
                    else None
                ),
                "probe": probe,
            }

    @classmethod
    async def start_background_stream(
        cls,
        camera_id: str,
        pipeline_callback,
        *,
        max_seconds: Optional[float] = None,
    ) -> bool:
        """Start an asynchronous background RTSP/video capture loop for a registered camera."""
        if camera_id in cls._active_streams and not cls._active_streams[camera_id].done():
            return True

        async with db_session.AsyncSessionLocal() as session:
            res = await session.execute(
                select(CctvCamera).where(CctvCamera.id == camera_id)
            )
            camera = res.scalar_one_or_none()
            if camera is None:
                return False
            source_type = camera.source_type
            source_uri = camera.source_uri
            org_id = camera.organization_id

        async def _runner() -> None:
            started_at = time.time()
            source: Any = source_uri or "0"
            if source_type == "webcam":
                try:
                    source = int(source)
                except (TypeError, ValueError):
                    source = 0

            cap = None
            try:
                if source_type == "simulated":
                    while True:
                        if max_seconds and (time.time() - started_at) > max_seconds:
                            break
                        frame = np.full((360, 640, 3), 125, dtype=np.uint8)
                        cv2.putText(
                            frame,
                            f"LIVE {datetime.now().strftime('%H:%M:%S')}",
                            (180, 180),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.9,
                            (240, 240, 240),
                            2,
                        )
                        telemetry = await cls.record_frame_telemetry(
                            camera_id, frame, 5.0, organization_id=org_id
                        )
                        if pipeline_callback:
                            await pipeline_callback(camera_id, telemetry["enhanced_frame"])
                        await asyncio.sleep(0.25)
                    return

                cap = await asyncio.to_thread(cv2.VideoCapture, source)
                if not cap.isOpened():
                    await cls.handle_camera_disconnection(
                        camera_id,
                        error_category="missing_stream",
                        message=f"Could not open video stream '{source}'.",
                        organization_id=org_id,
                    )
                    return

                while True:
                    if max_seconds and (time.time() - started_at) > max_seconds:
                        break
                    ok, frame = await asyncio.to_thread(cap.read)
                    if not ok or frame is None:
                        await cls.handle_camera_disconnection(
                            camera_id,
                            error_category="recording_failed",
                            message="Stream ended or returned empty frame.",
                            organization_id=org_id,
                        )
                        # Attempt automatic reconnection after brief backoff
                        await asyncio.sleep(2.0)
                        reconnect = await cls.attempt_reconnect(camera_id)
                        if not reconnect.get("reconnected"):
                            break
                        cap.release()
                        cap = await asyncio.to_thread(cv2.VideoCapture, source)
                        if not cap.isOpened():
                            break
                        continue

                    telemetry = await cls.record_frame_telemetry(
                        camera_id, frame, 5.0, organization_id=org_id
                    )
                    if pipeline_callback:
                        await pipeline_callback(camera_id, telemetry["enhanced_frame"])
                    await asyncio.sleep(0.2)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("[CctvMonitor] Stream loop error for %s: %s", camera_id, exc)
                await cls.handle_camera_disconnection(
                    camera_id,
                    error_category="processing_failure",
                    message=str(exc),
                    organization_id=org_id,
                )
            finally:
                if cap is not None:
                    cap.release()

        task = asyncio.create_task(_runner())
        cls._active_streams[camera_id] = task
        return True

    @classmethod
    async def stop_background_stream(cls, camera_id: str) -> bool:
        task = cls._active_streams.pop(camera_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            return True
        return False
