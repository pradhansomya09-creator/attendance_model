"""Advanced CCTV-Based Smart Attendance, Monitoring, Validation & Governance Routes."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
import ulid
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, or_, select

from api.deps import get_repository
from core.cipher import decrypt_local_data
from core.vision import analyze_and_enhance_frame, estimate_head_pose_and_occlusion
from database.models import (
    AcademicSchedule,
    AttendanceGroup,
    AttendanceMember,
    AttendanceRecord,
    AuditLog,
    CctvCamera,
    CctvCameraLog,
    CrossSectionException,
    SectionMismatchAlert,
    SmartAttendanceEvaluation,
    StudentAcademicProfile,
    UnknownStudentDetection,
)
from database.repository import AttendanceRepository
from services.cctv_monitor_service import CctvMonitorService
from services.ip_stream_service import (
    CameraHealthStatus,
    CameraStreamRegistry,
    iter_mjpeg_frames,
    probe_ip_stream,
    validate_ip_stream_url,
    verify_camera_connectivity,
)
from services.smart_attendance_engine import SmartAttendanceEngine
from time_utils import local_now

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cctv", tags=["cctv"])


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _today_str() -> str:
    return local_now().strftime("%Y-%m-%d")


def _org_filter(stmt, model, org_id: Optional[str]):
    if org_id is not None:
        return stmt.where(model.organization_id == org_id)
    return stmt.where(model.organization_id.is_(None))


def _serialize_camera(cam: CctvCamera, backup_code: Optional[str] = None) -> Dict[str, Any]:
    return {
        "id": cam.id,
        "name": cam.name,
        "camera_code": cam.camera_code,
        "source_type": cam.source_type,
        "source_uri": cam.source_uri,
        "supports_ir": cam.supports_ir,
        "department": cam.department,
        "building": cam.building,
        "classroom": cam.classroom,
        "assigned_group_id": cam.assigned_group_id,
        "backup_camera_id": cam.backup_camera_id,
        "backup_camera_code": backup_code,
        "status": cam.status,
        "recording_status": cam.recording_status,
        "quality_status": cam.quality_status,
        "quality_score": cam.quality_score,
        "fps": cam.fps,
        "reconnect_attempts": cam.reconnect_attempts,
        "last_frame_at": cam.last_frame_at.isoformat() if cam.last_frame_at else None,
        "last_connected_at": cam.last_connected_at.isoformat() if cam.last_connected_at else None,
        "disconnected_at": cam.disconnected_at.isoformat() if cam.disconnected_at else None,
        "is_active": cam.is_active,
        "simulated_fault": CctvMonitorService.get_simulated_fault(cam.id),
        "stream_running": (
            cam.id in CctvMonitorService._active_streams
            and not CctvMonitorService._active_streams[cam.id].done()
        ),
    }


def _serialize_schedule(s: AcademicSchedule) -> Dict[str, Any]:
    return {
        "id": s.id,
        "group_id": s.group_id,
        "department": s.department,
        "semester": s.semester,
        "section": s.section,
        "subject_code": s.subject_code,
        "subject_name": s.subject_name,
        "faculty_name": s.faculty_name,
        "classroom": s.classroom,
        "building": s.building,
        "camera_id": s.camera_id,
        "day_of_week": s.day_of_week,
        "start_time": s.start_time,
        "end_time": s.end_time,
        "late_after_minutes": s.late_after_minutes,
        "early_exit_minutes": s.early_exit_minutes,
        "min_presence_percent": s.min_presence_percent,
        "is_active": s.is_active,
    }


def _serialize_evaluation(
    ev: SmartAttendanceEvaluation,
    member: Optional[AttendanceMember] = None,
    profile: Optional[StudentAcademicProfile] = None,
) -> Dict[str, Any]:
    return {
        "id": ev.id,
        "schedule_id": ev.schedule_id,
        "group_id": ev.group_id,
        "camera_id": ev.camera_id,
        "date": ev.date,
        "member_id": ev.member_id,
        "person_id": ev.person_id,
        "student_name": member.name if member else None,
        "registration_number": profile.registration_number if profile else None,
        "student_section": (
            f"{profile.department} {profile.semester}-{profile.section}"
            if profile
            else None
        ),
        "tracking_id": ev.tracking_id,
        "expected_section": ev.expected_section,
        "detected_section": ev.detected_section,
        "classification": ev.classification,
        "attendance_rule_status": ev.attendance_rule_status,
        "recognition_confidence": round(float(ev.recognition_confidence), 3),
        "image_quality_score": round(float(ev.image_quality_score), 3),
        "face_visibility_score": round(float(ev.face_visibility_score), 3),
        "temporal_consistency_score": round(float(ev.temporal_consistency_score), 3),
        "head_pose_ok": ev.head_pose_ok,
        "duplicate_flagged": ev.duplicate_flagged,
        "first_seen_at": ev.first_seen_at.isoformat() if ev.first_seen_at else None,
        "last_seen_at": ev.last_seen_at.isoformat() if ev.last_seen_at else None,
        "estimated_duration_minutes": round(float(ev.estimated_duration_minutes), 1),
        "observations_count": ev.observations_count,
        "reason": ev.reason,
        "verified_by": ev.verified_by,
        "verified_at": ev.verified_at.isoformat() if ev.verified_at else None,
    }


# ---------------------------------------------------------------------------
# Pydantic Request Schemas
# ---------------------------------------------------------------------------


class CameraCreateRequest(BaseModel):
    name: str
    camera_code: str
    source_type: str = "webcam"  # webcam | rtsp | video_file | simulated
    source_uri: Optional[str] = "0"
    supports_ir: bool = False
    department: Optional[str] = None
    building: Optional[str] = None
    classroom: Optional[str] = None
    assigned_group_id: Optional[str] = None
    backup_camera_id: Optional[str] = None


class CameraUpdateRequest(BaseModel):
    name: Optional[str] = None
    camera_code: Optional[str] = None
    source_type: Optional[str] = None
    source_uri: Optional[str] = None
    supports_ir: Optional[bool] = None
    department: Optional[str] = None
    building: Optional[str] = None
    classroom: Optional[str] = None
    assigned_group_id: Optional[str] = None
    backup_camera_id: Optional[str] = None
    is_active: Optional[bool] = None


class SimulateFaultRequest(BaseModel):
    fault: Optional[str] = None  # offline | frozen | darkness | blur | recording_failed | null


class ReconnectRequest(BaseModel):
    clear_fault: bool = True


class ScheduleCreateRequest(BaseModel):
    group_id: Optional[str] = None
    department: str
    semester: str
    section: str
    subject_code: str
    subject_name: str
    faculty_name: str
    classroom: str
    building: Optional[str] = None
    camera_id: Optional[str] = None
    day_of_week: str = "*"
    start_time: str = "09:00"
    end_time: str = "10:00"
    late_after_minutes: int = 10
    early_exit_minutes: int = 10
    min_presence_percent: float = 60.0


class ScheduleUpdateRequest(BaseModel):
    group_id: Optional[str] = None
    department: Optional[str] = None
    semester: Optional[str] = None
    section: Optional[str] = None
    subject_code: Optional[str] = None
    subject_name: Optional[str] = None
    faculty_name: Optional[str] = None
    classroom: Optional[str] = None
    building: Optional[str] = None
    camera_id: Optional[str] = None
    day_of_week: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    late_after_minutes: Optional[int] = None
    early_exit_minutes: Optional[int] = None
    min_presence_percent: Optional[float] = None
    is_active: Optional[bool] = None


class StudentProfileUpsertRequest(BaseModel):
    registration_number: str
    department: str
    semester: str
    section: str
    biometric_consent_granted: bool = True
    non_biometric_opt_out: bool = False


class MismatchResolveRequest(BaseModel):
    action: str  # approve_exception | confirmed_mismatch | dismiss
    resolved_by: str = "Faculty"
    notes: Optional[str] = None
    exception_type: str = "combined_lecture"
    valid_date: Optional[str] = None


class ExceptionCreateRequest(BaseModel):
    member_id: str
    target_schedule_id: str
    exception_type: str = "combined_lecture"
    reason: str
    authorized_by: str = "Admin"
    valid_date: Optional[str] = None


class UnknownActionRequest(BaseModel):
    action: str  # verify_identity | register_student | mark_unverified | dismiss
    resolved_by: str = "Admin"
    notes: Optional[str] = None
    # For verify_identity:
    member_id: Optional[str] = None
    # For register_student:
    name: Optional[str] = None
    group_id: Optional[str] = None
    registration_number: Optional[str] = None
    department: Optional[str] = None
    semester: Optional[str] = None
    section: Optional[str] = None
    enroll_captured_face: bool = True


class VerifyEvaluationRequest(BaseModel):
    classification: str  # manually_verified_present | absent | pending_verification
    attendance_rule_status: Optional[str] = None
    verified_by: str = "Faculty"
    reason: str = Field(..., min_length=3)


class ManualFallbackEntry(BaseModel):
    member_id: str
    status: str  # present | absent | late_entry


class ManualFallbackRequest(BaseModel):
    schedule_id: Optional[str] = None
    group_id: Optional[str] = None
    date: Optional[str] = None
    verified_by: str = "Faculty"
    reason: str = Field(..., min_length=3)
    entries: List[ManualFallbackEntry]


class FinalizeScheduleRequest(BaseModel):
    date: Optional[str] = None
    verified_by: str = "Faculty"


# ---------------------------------------------------------------------------
# 1. Image Quality & Frame Analysis Diagnostic
# ---------------------------------------------------------------------------


@router.post("/analyze-frame")
async def analyze_cctv_frame(
    image: UploadFile = File(...),
    include_enhanced_preview: bool = False,
):
    """Run intelligent image quality detection, adaptive enhancement, and head-pose estimation."""
    contents = await image.read()
    arr = np.frombuffer(contents, np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        raise HTTPException(status_code=400, detail="Invalid image file")

    enhanced, quality = analyze_and_enhance_frame(frame)
    poses: List[Dict[str, Any]] = []
    try:
        from hooks import process_face_detection

        faces = await process_face_detection(
            enhanced, min_face_size=32, enable_liveness=False
        )
        for face in faces:
            pose = estimate_head_pose_and_occlusion(enhanced, face)
            poses.append({"bbox": face.get("bbox"), **pose.to_dict()})
    except Exception as exc:
        logger.debug("Optional face pose analysis skipped: %s", exc)

    resp: Dict[str, Any] = {"quality": quality.to_dict(), "faces_pose": poses}
    if include_enhanced_preview:
        ok, buf = cv2.imencode(".jpg", enhanced, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if ok:
            resp["enhanced_image_data_url"] = (
                "data:image/jpeg;base64," + base64.b64encode(bytes(buf)).decode("ascii")
            )
    return resp


# ---------------------------------------------------------------------------
# 2. CCTV Camera Management, Health Monitoring, Simulation & Logs
# ---------------------------------------------------------------------------


@router.get("/cameras")
async def list_cameras(
    department: Optional[str] = None,
    building: Optional[str] = None,
    classroom: Optional[str] = None,
    status: Optional[str] = None,
    repo: AttendanceRepository = Depends(get_repository),
):
    stmt = _org_filter(select(CctvCamera), CctvCamera, repo.organization_id)
    if department:
        stmt = stmt.where(CctvCamera.department == department)
    if building:
        stmt = stmt.where(CctvCamera.building == building)
    if classroom:
        stmt = stmt.where(CctvCamera.classroom == classroom)
    if status:
        stmt = stmt.where(CctvCamera.status == status)
    res = await repo.session.execute(stmt.order_by(CctvCamera.created_at.desc()))
    cameras = res.scalars().all()
    code_by_id = {c.id: c.camera_code for c in cameras}
    return [_serialize_camera(c, code_by_id.get(c.backup_camera_id)) for c in cameras]


@router.post("/cameras")
async def create_camera(
    payload: CameraCreateRequest,
    repo: AttendanceRepository = Depends(get_repository),
):
    cam = CctvCamera(
        id=ulid.ulid(),
        name=payload.name.strip(),
        camera_code=payload.camera_code.strip(),
        source_type=payload.source_type,
        source_uri=payload.source_uri,
        supports_ir=payload.supports_ir,
        department=payload.department,
        building=payload.building,
        classroom=payload.classroom,
        assigned_group_id=payload.assigned_group_id,
        backup_camera_id=payload.backup_camera_id,
        status="online",
        recording_status="idle",
        quality_status="green",
        quality_score=1.0,
        last_connected_at=_utc_now(),
        organization_id=repo.organization_id,
    )
    repo.session.add(cam)
    repo.session.add(
        AuditLog(
            id=ulid.ulid(),
            action="CCTV_CAMERA_CREATED",
            target_type="cctv_camera",
            target_id=cam.id,
            details=json.dumps({"name": cam.name, "camera_code": cam.camera_code}),
            organization_id=repo.organization_id,
        )
    )
    await repo.session.commit()
    await repo.session.refresh(cam)

    # Probe immediately to capture live status for simulated/webcam/rtsp
    probe = await CctvMonitorService.probe_camera_source(cam)
    cam.status = probe.get("status", cam.status)
    cam.recording_status = probe.get("recording_status", cam.recording_status)
    if probe.get("quality"):
        cam.quality_status = probe["quality"]["status"]
        cam.quality_score = float(probe["quality"]["score"])
    cam.fps = float(probe.get("fps", 0.0))
    if probe.get("connected"):
        cam.last_connected_at = _utc_now()
    else:
        cam.disconnected_at = _utc_now()
        await CctvMonitorService.log_camera_event(
            repo.session,
            camera_id=cam.id,
            error_category=probe.get("error_category", "disconnected"),
            severity="warning",
            message=probe.get("message", "Camera probe offline during registration."),
            recovery_status="pending",
            organization_id=repo.organization_id,
        )
    await repo.session.commit()
    await repo.session.refresh(cam)
    return _serialize_camera(cam)


@router.put("/cameras/{camera_id}")
async def update_camera(
    camera_id: str,
    payload: CameraUpdateRequest,
    repo: AttendanceRepository = Depends(get_repository),
):
    stmt = _org_filter(
        select(CctvCamera).where(CctvCamera.id == camera_id),
        CctvCamera,
        repo.organization_id,
    )
    cam = (await repo.session.execute(stmt)).scalar_one_or_none()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")

    for field_name, val in payload.model_dump(exclude_unset=True).items():
        setattr(cam, field_name, val)

    await repo.session.commit()
    await repo.session.refresh(cam)
    return _serialize_camera(cam)


@router.delete("/cameras/{camera_id}")
async def delete_camera(
    camera_id: str,
    repo: AttendanceRepository = Depends(get_repository),
):
    await CctvMonitorService.stop_background_stream(camera_id)
    stmt = _org_filter(
        select(CctvCamera).where(CctvCamera.id == camera_id),
        CctvCamera,
        repo.organization_id,
    )
    cam = (await repo.session.execute(stmt)).scalar_one_or_none()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")

    cam.is_active = False
    cam.status = "offline"
    repo.session.add(
        AuditLog(
            id=ulid.ulid(),
            action="CCTV_CAMERA_DEACTIVATED",
            target_type="cctv_camera",
            target_id=cam.id,
            details=json.dumps({"camera_code": cam.camera_code}),
            organization_id=repo.organization_id,
        )
    )
    await repo.session.commit()
    return {"success": True, "camera_id": camera_id}


@router.post("/cameras/{camera_id}/probe")
async def probe_camera(
    camera_id: str,
    repo: AttendanceRepository = Depends(get_repository),
):
    stmt = _org_filter(
        select(CctvCamera).where(CctvCamera.id == camera_id),
        CctvCamera,
        repo.organization_id,
    )
    cam = (await repo.session.execute(stmt)).scalar_one_or_none()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")

    probe = await CctvMonitorService.probe_camera_source(cam)
    now = _utc_now()
    cam.status = probe.get("status", "offline")
    cam.recording_status = probe.get("recording_status", "failed")
    if probe.get("quality"):
        cam.quality_status = probe["quality"]["status"]
        cam.quality_score = float(probe["quality"]["score"])
    if probe.get("fps") is not None:
        cam.fps = float(probe["fps"])

    if probe.get("connected") and cam.status == "online":
        cam.last_connected_at = now
        cam.last_frame_at = now
        cam.disconnected_at = None
        await CctvMonitorService.resolve_open_logs(
            repo.session,
            camera_id=cam.id,
            recovery_status="recovered",
            corrective_action="Probe succeeded and restored online status.",
        )
    else:
        cam.disconnected_at = cam.disconnected_at or now
        backup = await CctvMonitorService.find_backup_camera(repo.session, cam)
        await CctvMonitorService.log_camera_event(
            repo.session,
            camera_id=cam.id,
            error_category=probe.get("error_category", "disconnected"),
            severity="critical",
            message=probe.get("message", "Camera health probe failed."),
            recovery_status="backup_used" if backup else "pending",
            corrective_action=(
                f"Backup camera {backup.camera_code} active." if backup else None
            ),
            organization_id=repo.organization_id,
        )

    await repo.session.commit()
    await repo.session.refresh(cam)
    return {"camera": _serialize_camera(cam), "probe": probe}


@router.post("/cameras/{camera_id}/reconnect")
async def reconnect_camera(
    camera_id: str,
    payload: ReconnectRequest = ReconnectRequest(),
    repo: AttendanceRepository = Depends(get_repository),
):
    stmt = _org_filter(
        select(CctvCamera).where(CctvCamera.id == camera_id),
        CctvCamera,
        repo.organization_id,
    )
    cam = (await repo.session.execute(stmt)).scalar_one_or_none()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")

    result = await CctvMonitorService.attempt_reconnect(
        camera_id, clear_fault=payload.clear_fault
    )
    return result


@router.post("/cameras/{camera_id}/simulate")
async def simulate_camera_fault(
    camera_id: str,
    payload: SimulateFaultRequest,
    repo: AttendanceRepository = Depends(get_repository),
):
    stmt = _org_filter(
        select(CctvCamera).where(CctvCamera.id == camera_id),
        CctvCamera,
        repo.organization_id,
    )
    cam = (await repo.session.execute(stmt)).scalar_one_or_none()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")

    CctvMonitorService.set_simulated_fault(camera_id, payload.fault)
    if payload.fault in ("offline", "recording_failed"):
        res = await CctvMonitorService.handle_camera_disconnection(
            camera_id,
            error_category=(
                "disconnected" if payload.fault == "offline" else "recording_failed"
            ),
            message=f"Simulated camera fault activated: {payload.fault}",
            organization_id=repo.organization_id,
        )
        return {"simulated": payload.fault, "recovery": res}

    if payload.fault is None:
        res = await CctvMonitorService.attempt_reconnect(camera_id, clear_fault=True)
        return {"simulated": None, "recovery": res}

    # frozen / darkness / blur -> run probe & reflect immediately in DB
    return await probe_camera(camera_id, repo=repo)


@router.post("/cameras/{camera_id}/start-stream")
async def start_camera_stream(
    camera_id: str,
    repo: AttendanceRepository = Depends(get_repository),
):
    stmt = _org_filter(
        select(CctvCamera).where(CctvCamera.id == camera_id),
        CctvCamera,
        repo.organization_id,
    )
    cam = (await repo.session.execute(stmt)).scalar_one_or_none()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")

    started = await CctvMonitorService.start_background_stream(camera_id, None)
    return {"started": started, "camera_id": camera_id}


@router.post("/cameras/{camera_id}/stop-stream")
async def stop_camera_stream(
    camera_id: str,
    repo: AttendanceRepository = Depends(get_repository),
):
    stopped = await CctvMonitorService.stop_background_stream(camera_id)
    return {"stopped": stopped, "camera_id": camera_id}


@router.get("/cameras/logs")
async def list_camera_logs(
    camera_id: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
    repo: AttendanceRepository = Depends(get_repository),
):
    stmt = _org_filter(select(CctvCameraLog), CctvCameraLog, repo.organization_id)
    if camera_id:
        stmt = stmt.where(CctvCameraLog.camera_id == camera_id)
    logs = (
        await repo.session.execute(
            stmt.order_by(CctvCameraLog.detected_at.desc()).limit(limit)
        )
    ).scalars().all()

    cams_res = await repo.session.execute(
        _org_filter(select(CctvCamera), CctvCamera, repo.organization_id)
    )
    cams = {c.id: c for c in cams_res.scalars().all()}

    return [
        {
            "id": l.id,
            "camera_id": l.camera_id,
            "camera_name": cams[l.camera_id].name if l.camera_id in cams else l.camera_id,
            "camera_code": cams[l.camera_id].camera_code if l.camera_id in cams else None,
            "classroom": cams[l.camera_id].classroom if l.camera_id in cams else None,
            "error_category": l.error_category,
            "severity": l.severity,
            "message": l.message,
            "detected_at": l.detected_at.isoformat() if l.detected_at else None,
            "resolved_at": l.resolved_at.isoformat() if l.resolved_at else None,
            "duration_seconds": l.duration_seconds,
            "recovery_status": l.recovery_status,
            "corrective_action": l.corrective_action,
        }
        for l in logs
    ]


@router.get("/admin/overview")
async def get_admin_overview(
    repo: AttendanceRepository = Depends(get_repository),
):
    cams = (
        await repo.session.execute(
            _org_filter(select(CctvCamera), CctvCamera, repo.organization_id).where(
                CctvCamera.is_active.is_(True)
            )
        )
    ).scalars().all()

    open_logs = (
        await repo.session.execute(
            _org_filter(select(CctvCameraLog), CctvCameraLog, repo.organization_id).where(
                CctvCameraLog.resolved_at.is_(None)
            )
        )
    ).scalars().all()

    pending_unknowns = (
        await repo.session.execute(
            _org_filter(
                select(UnknownStudentDetection),
                UnknownStudentDetection,
                repo.organization_id,
            ).where(UnknownStudentDetection.status == "pending")
        )
    ).scalars().all()

    open_mismatches = (
        await repo.session.execute(
            _org_filter(
                select(SectionMismatchAlert),
                SectionMismatchAlert,
                repo.organization_id,
            ).where(SectionMismatchAlert.status == "open")
        )
    ).scalars().all()

    from core.lifespan import face_detector, face_recognizer, liveness_detector

    enrolled_persons = 0
    if face_recognizer and hasattr(face_recognizer, "get_all_persons"):
        try:
            persons = await face_recognizer.get_all_persons(repo.organization_id)
            enrolled_persons = len(persons)
        except Exception:
            pass

    return {
        "cameras": {
            "total": len(cams),
            "online": sum(1 for c in cams if c.status == "online"),
            "unstable": sum(1 for c in cams if c.status == "unstable"),
            "offline": sum(1 for c in cams if c.status == "offline"),
            "recording_failed": sum(
                1 for c in cams if c.status == "recording_failed"
            ),
            "quality_green": sum(1 for c in cams if c.quality_status == "green"),
            "quality_yellow": sum(1 for c in cams if c.quality_status == "yellow"),
            "quality_red": sum(1 for c in cams if c.quality_status == "red"),
            "with_backup": sum(1 for c in cams if c.backup_camera_id),
        },
        "alerts": {
            "open_camera_incidents": len(open_logs),
            "pending_unknown_students": len(pending_unknowns),
            "open_section_mismatches": len(open_mismatches),
        },
        "model_health": {
            "detector_loaded": face_detector is not None,
            "recognizer_loaded": face_recognizer is not None,
            "liveness_loaded": liveness_detector is not None,
            "enrolled_embeddings": enrolled_persons,
            "similarity_threshold": (
                getattr(face_recognizer, "similarity_threshold", None)
                if face_recognizer
                else None
            ),
        },
    }


# ---------------------------------------------------------------------------
# 3. Academic Timetable Schedules & Student Academic Profiles
# ---------------------------------------------------------------------------


@router.get("/schedules")
async def list_schedules(
    department: Optional[str] = None,
    semester: Optional[str] = None,
    section: Optional[str] = None,
    group_id: Optional[str] = None,
    repo: AttendanceRepository = Depends(get_repository),
):
    stmt = _org_filter(
        select(AcademicSchedule), AcademicSchedule, repo.organization_id
    )
    if department:
        stmt = stmt.where(AcademicSchedule.department == department)
    if semester:
        stmt = stmt.where(AcademicSchedule.semester == semester)
    if section:
        stmt = stmt.where(AcademicSchedule.section == section)
    if group_id:
        stmt = stmt.where(AcademicSchedule.group_id == group_id)
    rows = (
        await repo.session.execute(stmt.order_by(AcademicSchedule.start_time.asc()))
    ).scalars().all()
    return [_serialize_schedule(s) for s in rows]


@router.post("/schedules")
async def create_schedule(
    payload: ScheduleCreateRequest,
    repo: AttendanceRepository = Depends(get_repository),
):
    sched = AcademicSchedule(
        id=ulid.ulid(),
        group_id=payload.group_id,
        department=payload.department.strip(),
        semester=payload.semester.strip(),
        section=payload.section.strip(),
        subject_code=payload.subject_code.strip(),
        subject_name=payload.subject_name.strip(),
        faculty_name=payload.faculty_name.strip(),
        classroom=payload.classroom.strip(),
        building=payload.building,
        camera_id=payload.camera_id,
        day_of_week=payload.day_of_week,
        start_time=payload.start_time,
        end_time=payload.end_time,
        late_after_minutes=payload.late_after_minutes,
        early_exit_minutes=payload.early_exit_minutes,
        min_presence_percent=payload.min_presence_percent,
        is_active=True,
        organization_id=repo.organization_id,
    )
    repo.session.add(sched)
    repo.session.add(
        AuditLog(
            id=ulid.ulid(),
            action="ACADEMIC_SCHEDULE_CREATED",
            target_type="academic_schedule",
            target_id=sched.id,
            details=json.dumps(
                {
                    "section": f"{sched.department} {sched.semester}-{sched.section}",
                    "subject": sched.subject_code,
                    "classroom": sched.classroom,
                }
            ),
            organization_id=repo.organization_id,
        )
    )
    await repo.session.commit()
    await repo.session.refresh(sched)
    return _serialize_schedule(sched)


@router.put("/schedules/{schedule_id}")
async def update_schedule(
    schedule_id: str,
    payload: ScheduleUpdateRequest,
    repo: AttendanceRepository = Depends(get_repository),
):
    stmt = _org_filter(
        select(AcademicSchedule).where(AcademicSchedule.id == schedule_id),
        AcademicSchedule,
        repo.organization_id,
    )
    sched = (await repo.session.execute(stmt)).scalar_one_or_none()
    if not sched:
        raise HTTPException(status_code=404, detail="Schedule not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(sched, k, v)
    await repo.session.commit()
    await repo.session.refresh(sched)
    return _serialize_schedule(sched)


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(
    schedule_id: str,
    repo: AttendanceRepository = Depends(get_repository),
):
    stmt = _org_filter(
        select(AcademicSchedule).where(AcademicSchedule.id == schedule_id),
        AcademicSchedule,
        repo.organization_id,
    )
    sched = (await repo.session.execute(stmt)).scalar_one_or_none()
    if not sched:
        raise HTTPException(status_code=404, detail="Schedule not found")
    sched.is_active = False
    await repo.session.commit()
    return {"success": True, "schedule_id": schedule_id}


@router.get("/student-profiles")
async def list_student_profiles(
    group_id: Optional[str] = None,
    department: Optional[str] = None,
    section: Optional[str] = None,
    repo: AttendanceRepository = Depends(get_repository),
):
    m_stmt = _org_filter(
        select(AttendanceMember).where(AttendanceMember.is_deleted.is_(False)),
        AttendanceMember,
        repo.organization_id,
    )
    if group_id:
        m_stmt = m_stmt.where(AttendanceMember.group_id == group_id)
    members = (await repo.session.execute(m_stmt.order_by(AttendanceMember.name.asc()))).scalars().all()

    p_stmt = _org_filter(
        select(StudentAcademicProfile), StudentAcademicProfile, repo.organization_id
    )
    profiles = {
        p.member_id: p
        for p in (await repo.session.execute(p_stmt)).scalars().all()
    }

    rows = []
    for m in members:
        p = profiles.get(m.id)
        if department and (not p or p.department != department):
            continue
        if section and (not p or p.section != section):
            continue
        rows.append(
            {
                "member_id": m.id,
                "person_id": m.person_id,
                "name": m.name,
                "group_id": m.group_id,
                "role": m.role,
                "registration_number": p.registration_number if p else None,
                "department": p.department if p else None,
                "semester": p.semester if p else None,
                "section": p.section if p else None,
                "biometric_consent_granted": (
                    p.biometric_consent_granted if p else True
                ),
                "non_biometric_opt_out": p.non_biometric_opt_out if p else False,
                "consent_timestamp": (
                    p.consent_timestamp.isoformat()
                    if p and p.consent_timestamp
                    else None
                ),
            }
        )
    return rows


@router.put("/student-profiles/{member_id}")
async def upsert_student_profile(
    member_id: str,
    payload: StudentProfileUpsertRequest,
    repo: AttendanceRepository = Depends(get_repository),
):
    member = await repo.get_member_by_id(member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    res = await repo.session.execute(
        select(StudentAcademicProfile).where(
            StudentAcademicProfile.member_id == member_id
        )
    )
    prof = res.scalar_one_or_none()
    now = _utc_now()
    if prof is None:
        prof = StudentAcademicProfile(
            member_id=member_id,
            registration_number=payload.registration_number.strip(),
            department=payload.department.strip(),
            semester=payload.semester.strip(),
            section=payload.section.strip(),
            biometric_consent_granted=payload.biometric_consent_granted,
            non_biometric_opt_out=payload.non_biometric_opt_out,
            consent_timestamp=now,
            organization_id=repo.organization_id,
        )
        repo.session.add(prof)
    else:
        prof.registration_number = payload.registration_number.strip()
        prof.department = payload.department.strip()
        prof.semester = payload.semester.strip()
        prof.section = payload.section.strip()
        prof.biometric_consent_granted = payload.biometric_consent_granted
        prof.non_biometric_opt_out = payload.non_biometric_opt_out
        prof.consent_timestamp = now

    repo.session.add(
        AuditLog(
            id=ulid.ulid(),
            action="STUDENT_PROFILE_CONSENT_UPDATED",
            target_type="student_academic_profile",
            target_id=member_id,
            details=json.dumps(
                {
                    "registration_number": prof.registration_number,
                    "section": f"{prof.department} {prof.semester}-{prof.section}",
                    "biometric_consent_granted": prof.biometric_consent_granted,
                    "non_biometric_opt_out": prof.non_biometric_opt_out,
                }
            ),
            organization_id=repo.organization_id,
        )
    )
    await repo.session.commit()
    return {
        "member_id": prof.member_id,
        "registration_number": prof.registration_number,
        "department": prof.department,
        "semester": prof.semester,
        "section": prof.section,
        "biometric_consent_granted": prof.biometric_consent_granted,
        "non_biometric_opt_out": prof.non_biometric_opt_out,
        "consent_timestamp": prof.consent_timestamp.isoformat() if prof.consent_timestamp else None,
    }


# ---------------------------------------------------------------------------
# 4. Cross-Section Mismatches & Exceptions
# ---------------------------------------------------------------------------


@router.get("/section-mismatches")
async def list_section_mismatches(
    status: Optional[str] = None,
    schedule_id: Optional[str] = None,
    repo: AttendanceRepository = Depends(get_repository),
):
    stmt = _org_filter(
        select(SectionMismatchAlert), SectionMismatchAlert, repo.organization_id
    )
    if status:
        stmt = stmt.where(SectionMismatchAlert.status == status)
    if schedule_id:
        stmt = stmt.where(SectionMismatchAlert.schedule_id == schedule_id)
    rows = (
        await repo.session.execute(stmt.order_by(SectionMismatchAlert.detected_at.desc()))
    ).scalars().all()
    return [
        {
            "id": a.id,
            "member_id": a.member_id,
            "person_id": a.person_id,
            "student_name": a.student_name,
            "registration_number": a.registration_number,
            "actual_section": a.actual_section,
            "scheduled_section": a.scheduled_section,
            "schedule_id": a.schedule_id,
            "camera_id": a.camera_id,
            "classroom": a.classroom,
            "detected_at": a.detected_at.isoformat() if a.detected_at else None,
            "status": a.status,
            "resolved_by": a.resolved_by,
            "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
            "notes": a.notes,
        }
        for a in rows
    ]


@router.post("/section-mismatches/{alert_id}/resolve")
async def resolve_section_mismatch(
    alert_id: str,
    payload: MismatchResolveRequest,
    repo: AttendanceRepository = Depends(get_repository),
):
    stmt = _org_filter(
        select(SectionMismatchAlert).where(SectionMismatchAlert.id == alert_id),
        SectionMismatchAlert,
        repo.organization_id,
    )
    alert = (await repo.session.execute(stmt)).scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Section mismatch alert not found")

    now = _utc_now()
    valid_date = payload.valid_date or _today_str()
    if payload.action == "approve_exception":
        if not alert.schedule_id:
            raise HTTPException(
                status_code=400, detail="Alert has no target schedule to attach exception"
            )
        exc = CrossSectionException(
            id=ulid.ulid(),
            member_id=alert.member_id,
            person_id=alert.person_id,
            from_section=alert.actual_section,
            target_schedule_id=alert.schedule_id,
            target_section=alert.scheduled_section,
            exception_type=payload.exception_type,
            reason=payload.notes or "Approved inter-section attendance exception.",
            authorized_by=payload.resolved_by,
            valid_date=valid_date,
            status="approved",
            organization_id=repo.organization_id,
        )
        repo.session.add(exc)
        alert.status = "exception_approved"

        # Upgrade matching evaluation to manually_verified_present
        ev_res = await repo.session.execute(
            select(SmartAttendanceEvaluation).where(
                SmartAttendanceEvaluation.member_id == alert.member_id,
                SmartAttendanceEvaluation.schedule_id == alert.schedule_id,
                SmartAttendanceEvaluation.date == valid_date,
            )
        )
        ev = ev_res.scalar_one_or_none()
        if ev is not None:
            ev.classification = "manually_verified_present"
            ev.verified_by = payload.resolved_by
            ev.verified_at = now
            ev.reason = f"Cross-section exception approved ({payload.exception_type})."
    elif payload.action == "dismiss":
        alert.status = "dismissed"
    else:
        alert.status = "confirmed_mismatch"

    alert.resolved_by = payload.resolved_by
    alert.resolved_at = now
    alert.notes = payload.notes
    repo.session.add(
        AuditLog(
            id=ulid.ulid(),
            action="SECTION_MISMATCH_RESOLVED",
            target_type="section_mismatch_alert",
            target_id=alert.id,
            details=json.dumps(
                {
                    "action": payload.action,
                    "resolved_by": payload.resolved_by,
                    "notes": payload.notes,
                }
            ),
            organization_id=repo.organization_id,
        )
    )
    await repo.session.commit()
    return {"success": True, "status": alert.status}


@router.get("/exceptions")
async def list_exceptions(
    target_schedule_id: Optional[str] = None,
    repo: AttendanceRepository = Depends(get_repository),
):
    stmt = _org_filter(
        select(CrossSectionException), CrossSectionException, repo.organization_id
    )
    if target_schedule_id:
        stmt = stmt.where(CrossSectionException.target_schedule_id == target_schedule_id)
    rows = (
        await repo.session.execute(stmt.order_by(CrossSectionException.created_at.desc()))
    ).scalars().all()

    members_res = await repo.session.execute(
        _org_filter(select(AttendanceMember), AttendanceMember, repo.organization_id)
    )
    names = {m.id: m.name for m in members_res.scalars().all()}

    return [
        {
            "id": e.id,
            "member_id": e.member_id,
            "person_id": e.person_id,
            "student_name": names.get(e.member_id),
            "from_section": e.from_section,
            "target_schedule_id": e.target_schedule_id,
            "target_section": e.target_section,
            "exception_type": e.exception_type,
            "reason": e.reason,
            "authorized_by": e.authorized_by,
            "valid_date": e.valid_date,
            "status": e.status,
        }
        for e in rows
    ]


@router.post("/exceptions")
async def create_exception(
    payload: ExceptionCreateRequest,
    repo: AttendanceRepository = Depends(get_repository),
):
    member = await repo.get_member_by_id(payload.member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    sched = (
        await repo.session.execute(
            select(AcademicSchedule).where(AcademicSchedule.id == payload.target_schedule_id)
        )
    ).scalar_one_or_none()
    if not sched:
        raise HTTPException(status_code=404, detail="Schedule not found")
    prof = (
        await repo.session.execute(
            select(StudentAcademicProfile).where(
                StudentAcademicProfile.member_id == member.id
            )
        )
    ).scalar_one_or_none()
    from_sec = (
        f"{prof.department} {prof.semester}-{prof.section}" if prof else "Unassigned"
    )
    target_sec = f"{sched.department} {sched.semester}-{sched.section}"
    exc = CrossSectionException(
        id=ulid.ulid(),
        member_id=member.id,
        person_id=member.person_id,
        from_section=from_sec,
        target_schedule_id=sched.id,
        target_section=target_sec,
        exception_type=payload.exception_type,
        reason=payload.reason,
        authorized_by=payload.authorized_by,
        valid_date=payload.valid_date or _today_str(),
        status="approved",
        organization_id=repo.organization_id,
    )
    repo.session.add(exc)
    repo.session.add(
        AuditLog(
            id=ulid.ulid(),
            action="CROSS_SECTION_EXCEPTION_GRANTED",
            target_type="cross_section_exception",
            target_id=exc.id,
            details=json.dumps(
                {
                    "member_id": member.id,
                    "schedule_id": sched.id,
                    "authorized_by": payload.authorized_by,
                    "reason": payload.reason,
                }
            ),
            organization_id=repo.organization_id,
        )
    )
    await repo.session.commit()
    return {"id": exc.id, "status": exc.status}


@router.post("/exceptions/{exception_id}/revoke")
async def revoke_exception(
    exception_id: str,
    repo: AttendanceRepository = Depends(get_repository),
):
    stmt = _org_filter(
        select(CrossSectionException).where(CrossSectionException.id == exception_id),
        CrossSectionException,
        repo.organization_id,
    )
    exc = (await repo.session.execute(stmt)).scalar_one_or_none()
    if not exc:
        raise HTTPException(status_code=404, detail="Exception not found")
    exc.status = "revoked"
    await repo.session.commit()
    return {"success": True, "status": "revoked"}


# ---------------------------------------------------------------------------
# 5. Unknown Student Captures & Registration Workflow
# ---------------------------------------------------------------------------


@router.get("/unknown-detections")
async def list_unknown_detections(
    status: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=300),
    repo: AttendanceRepository = Depends(get_repository),
):
    stmt = _org_filter(
        select(UnknownStudentDetection),
        UnknownStudentDetection,
        repo.organization_id,
    )
    if status:
        stmt = stmt.where(UnknownStudentDetection.status == status)
    rows = (
        await repo.session.execute(
            stmt.order_by(UnknownStudentDetection.detected_at.desc()).limit(limit)
        )
    ).scalars().all()

    return [
        {
            "id": u.id,
            "tracking_id": u.tracking_id,
            "camera_id": u.camera_id,
            "schedule_id": u.schedule_id,
            "group_id": u.group_id,
            "classroom": u.classroom,
            "detected_at": u.detected_at.isoformat() if u.detected_at else None,
            "snapshot_data_url": SmartAttendanceEngine.decrypt_snapshot_data_url(
                u.frame_snapshot_enc
            ),
            "confidence_best_guess": round(float(u.confidence_best_guess), 3),
            "status": u.status,
            "resolved_member_id": u.resolved_member_id,
            "resolved_by": u.resolved_by,
            "resolved_at": u.resolved_at.isoformat() if u.resolved_at else None,
            "notes": u.notes,
        }
        for u in rows
    ]


@router.get("/unknown-detections/search-students")
async def search_existing_students(
    q: str = Query(default="", min_length=0),
    repo: AttendanceRepository = Depends(get_repository),
):
    stmt = _org_filter(
        select(AttendanceMember).where(AttendanceMember.is_deleted.is_(False)),
        AttendanceMember,
        repo.organization_id,
    )
    members = (await repo.session.execute(stmt.order_by(AttendanceMember.name.asc()))).scalars().all()
    profiles = {
        p.member_id: p
        for p in (
            await repo.session.execute(
                _org_filter(
                    select(StudentAcademicProfile),
                    StudentAcademicProfile,
                    repo.organization_id,
                )
            )
        ).scalars().all()
    }
    term = q.strip().lower()
    results = []
    for m in members:
        p = profiles.get(m.id)
        reg = p.registration_number if p else ""
        if term and not (
            term in m.name.lower()
            or term in m.person_id.lower()
            or term in reg.lower()
        ):
            continue
        results.append(
            {
                "member_id": m.id,
                "person_id": m.person_id,
                "name": m.name,
                "group_id": m.group_id,
                "registration_number": p.registration_number if p else None,
                "department": p.department if p else None,
                "semester": p.semester if p else None,
                "section": p.section if p else None,
            }
        )
    return results[:50]


@router.post("/unknown-detections/{detection_id}/action")
async def act_on_unknown_detection(
    detection_id: str,
    payload: UnknownActionRequest,
    repo: AttendanceRepository = Depends(get_repository),
):
    stmt = _org_filter(
        select(UnknownStudentDetection).where(
            UnknownStudentDetection.id == detection_id
        ),
        UnknownStudentDetection,
        repo.organization_id,
    )
    det = (await repo.session.execute(stmt)).scalar_one_or_none()
    if not det:
        raise HTTPException(status_code=404, detail="Unknown student detection not found")

    now = _utc_now()
    resolved_member: Optional[AttendanceMember] = None

    if payload.action == "verify_identity":
        if not payload.member_id:
            raise HTTPException(status_code=400, detail="member_id is required")
        resolved_member = await repo.get_member_by_id(payload.member_id)
        if not resolved_member:
            raise HTTPException(status_code=404, detail="Student member not found")
        det.status = "verified"
        det.resolved_member_id = resolved_member.id
        det.resolved_by = payload.resolved_by
        det.resolved_at = now
        det.notes = payload.notes or f"Identity verified as {resolved_member.name}"

    elif payload.action == "register_student":
        if not payload.name or not (payload.group_id or det.group_id):
            raise HTTPException(
                status_code=400, detail="name and group_id are required to register student"
            )
        target_group_id = payload.group_id or det.group_id
        group = await repo.get_group(target_group_id)
        if not group:
            raise HTTPException(status_code=404, detail="Target group not found")

        person_id = ulid.ulid()
        resolved_member = await repo.add_member(
            {
                "name": payload.name.strip(),
                "person_id": person_id,
                "group_id": target_group_id,
                "role": "student",
                "is_active": True,
            }
        )
        if payload.registration_number:
            repo.session.add(
                StudentAcademicProfile(
                    member_id=resolved_member.id,
                    registration_number=payload.registration_number.strip(),
                    department=(payload.department or "General").strip(),
                    semester=(payload.semester or "1").strip(),
                    section=(payload.section or "A").strip(),
                    biometric_consent_granted=True,
                    non_biometric_opt_out=False,
                    consent_timestamp=now,
                    organization_id=repo.organization_id,
                )
            )

        # Persist captured encrypted face embedding into Face database if present
        if payload.enroll_captured_face and det.embedding_enc:
            try:
                from core.lifespan import face_recognizer

                raw_emb = decrypt_local_data(det.embedding_enc)
                vec = np.frombuffer(raw_emb, dtype=np.float32)
                if face_recognizer and hasattr(face_recognizer, "_get_db_manager"):
                    db_mgr = face_recognizer._get_db_manager(repo.organization_id)
                    if db_mgr:
                        img_hash = hashlib.sha256(
                            det.frame_snapshot_enc or raw_emb
                        ).hexdigest()[:16]
                        await db_mgr.add_person(person_id, vec, img_hash)
                        await face_recognizer.refresh_cache(repo.organization_id)
            except Exception as emb_err:
                logger.warning("Failed enrolling captured unknown embedding: %s", emb_err)

        from services.live_stream_service import LiveStreamService

        LiveStreamService.invalidate_all(repo.organization_id)

        det.status = "verified"
        det.resolved_member_id = resolved_member.id
        det.resolved_by = payload.resolved_by
        det.resolved_at = now
        det.notes = payload.notes or f"Registered new student {resolved_member.name}"

    elif payload.action == "mark_unverified":
        det.status = "unverified"
        det.resolved_by = payload.resolved_by
        det.resolved_at = now
        det.notes = payload.notes or "Marked as unverified by administrator."

    elif payload.action == "dismiss":
        det.status = "dismissed"
        det.resolved_by = payload.resolved_by
        det.resolved_at = now
        det.notes = payload.notes or "Dismissed incorrect face detection."
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported action '{payload.action}'")

    # Update associated SmartAttendanceEvaluation by tracking_id if present
    ev_stmt = _org_filter(
        select(SmartAttendanceEvaluation).where(
            SmartAttendanceEvaluation.tracking_id == det.tracking_id
        ),
        SmartAttendanceEvaluation,
        repo.organization_id,
    )
    ev = (await repo.session.execute(ev_stmt)).scalar_one_or_none()
    if ev is not None:
        if resolved_member is not None:
            ev.member_id = resolved_member.id
            ev.person_id = resolved_member.person_id
            ev.classification = "manually_verified_present"
            ev.attendance_rule_status = "full_attendance"
            ev.verified_by = payload.resolved_by
            ev.verified_at = now
            ev.reason = det.notes
        elif payload.action == "dismiss":
            ev.classification = "absent"
            ev.attendance_rule_status = "absent"
            ev.reason = det.notes

    repo.session.add(
        AuditLog(
            id=ulid.ulid(),
            action=f"UNKNOWN_DETECTION_{payload.action.upper()}",
            target_type="unknown_student_detection",
            target_id=det.id,
            details=json.dumps(
                {
                    "resolved_by": payload.resolved_by,
                    "resolved_member_id": det.resolved_member_id,
                    "notes": det.notes,
                }
            ),
            organization_id=repo.organization_id,
        )
    )
    await repo.session.commit()
    return {
        "success": True,
        "status": det.status,
        "resolved_member_id": det.resolved_member_id,
    }


@router.post("/unknown-detections/reconcile")
async def reconcile_unknowns(
    repo: AttendanceRepository = Depends(get_repository),
):
    from core.lifespan import face_recognizer

    matches = await SmartAttendanceEngine.reconcile_unknowns_for_newly_registered(
        repo.session,
        face_recognizer=face_recognizer,
        organization_id=repo.organization_id,
    )
    await repo.session.commit()
    return {"matched_count": len(matches), "matches": matches}


# ---------------------------------------------------------------------------
# 6. Faculty Classroom Monitor, Manual Verification, Fallback & Finalization
# ---------------------------------------------------------------------------


@router.get("/faculty/monitor")
async def get_faculty_monitor(
    schedule_id: Optional[str] = None,
    group_id: Optional[str] = None,
    date: Optional[str] = None,
    repo: AttendanceRepository = Depends(get_repository),
):
    date_str = date or _today_str()
    sched = None
    if schedule_id:
        sched = (
            await repo.session.execute(
                _org_filter(
                    select(AcademicSchedule).where(AcademicSchedule.id == schedule_id),
                    AcademicSchedule,
                    repo.organization_id,
                )
            )
        ).scalar_one_or_none()
        if sched and not group_id:
            group_id = sched.group_id

    cam = None
    backup_cam = None
    cam_id = sched.camera_id if sched else None
    if not cam_id and group_id:
        cam = (
            await repo.session.execute(
                _org_filter(
                    select(CctvCamera).where(
                        CctvCamera.assigned_group_id == group_id,
                        CctvCamera.is_active.is_(True),
                    ),
                    CctvCamera,
                    repo.organization_id,
                )
            )
        ).scalars().first()
    elif cam_id:
        cam = (
            await repo.session.execute(
                select(CctvCamera).where(CctvCamera.id == cam_id)
            )
        ).scalar_one_or_none()

    if cam and cam.status in ("offline", "recording_failed"):
        backup_cam = await CctvMonitorService.find_backup_camera(repo.session, cam)

    # Enrolled members for manual fallback list
    enrolled_members: List[AttendanceMember] = []
    if group_id and group_id != "all":
        enrolled_members = (
            await repo.session.execute(
                _org_filter(
                    select(AttendanceMember).where(
                        AttendanceMember.group_id == group_id,
                        AttendanceMember.is_active.is_(True),
                        AttendanceMember.is_deleted.is_(False),
                    ),
                    AttendanceMember,
                    repo.organization_id,
                ).order_by(AttendanceMember.name.asc())
            )
        ).scalars().all()

    profiles = {
        p.member_id: p
        for p in (
            await repo.session.execute(
                _org_filter(
                    select(StudentAcademicProfile),
                    StudentAcademicProfile,
                    repo.organization_id,
                )
            )
        ).scalars().all()
    }
    member_by_id = {m.id: m for m in enrolled_members}

    e_stmt = _org_filter(
        select(SmartAttendanceEvaluation).where(
            SmartAttendanceEvaluation.date == date_str
        ),
        SmartAttendanceEvaluation,
        repo.organization_id,
    )
    if schedule_id:
        e_stmt = e_stmt.where(SmartAttendanceEvaluation.schedule_id == schedule_id)
    elif group_id and group_id != "all":
        e_stmt = e_stmt.where(SmartAttendanceEvaluation.group_id == group_id)

    evals = (
        await repo.session.execute(
            e_stmt.order_by(SmartAttendanceEvaluation.updated_at.desc())
        )
    ).scalars().all()

    # Fetch any extra members referenced by section mismatches
    for ev in evals:
        if ev.member_id and ev.member_id not in member_by_id:
            extra_m = await repo.get_member_by_id(ev.member_id)
            if extra_m:
                member_by_id[extra_m.id] = extra_m

    headcount = await SmartAttendanceEngine.compute_headcount_reconciliation(
        repo.session,
        group_id=group_id,
        schedule_id=schedule_id,
        date_str=date_str,
        organization_id=repo.organization_id,
    )

    m_stmt = _org_filter(
        select(SectionMismatchAlert).where(SectionMismatchAlert.status == "open"),
        SectionMismatchAlert,
        repo.organization_id,
    )
    if schedule_id:
        m_stmt = m_stmt.where(SectionMismatchAlert.schedule_id == schedule_id)
    open_mismatches = (await repo.session.execute(m_stmt)).scalars().all()

    eval_by_member = {ev.member_id: ev for ev in evals if ev.member_id}
    roster = [
        {
            "member_id": m.id,
            "person_id": m.person_id,
            "name": m.name,
            "registration_number": (
                profiles[m.id].registration_number if m.id in profiles else None
            ),
            "section": (
                f"{profiles[m.id].department} {profiles[m.id].semester}-{profiles[m.id].section}"
                if m.id in profiles
                else None
            ),
            "non_biometric_opt_out": bool(
                m.id in profiles and profiles[m.id].non_biometric_opt_out
            ),
            "current_classification": (
                eval_by_member[m.id].classification if m.id in eval_by_member else "unmarked"
            ),
            "current_rule_status": (
                eval_by_member[m.id].attendance_rule_status
                if m.id in eval_by_member
                else "unmarked"
            ),
        }
        for m in enrolled_members
    ]

    return {
        "date": date_str,
        "schedule": _serialize_schedule(sched) if sched else None,
        "camera": _serialize_camera(cam, backup_cam.camera_code if backup_cam else None)
        if cam
        else None,
        "backup_camera": _serialize_camera(backup_cam) if backup_cam else None,
        "headcount": headcount,
        "evaluations": [
            _serialize_evaluation(
                ev,
                member_by_id.get(ev.member_id),
                profiles.get(ev.member_id),
            )
            for ev in evals
        ],
        "open_mismatches": [
            {
                "id": a.id,
                "student_name": a.student_name,
                "registration_number": a.registration_number,
                "actual_section": a.actual_section,
                "scheduled_section": a.scheduled_section,
                "detected_at": a.detected_at.isoformat() if a.detected_at else None,
            }
            for a in open_mismatches
        ],
        "roster": roster,
    }


@router.post("/evaluations/{evaluation_id}/verify")
async def verify_evaluation(
    evaluation_id: str,
    payload: VerifyEvaluationRequest,
    repo: AttendanceRepository = Depends(get_repository),
):
    stmt = _org_filter(
        select(SmartAttendanceEvaluation).where(
            SmartAttendanceEvaluation.id == evaluation_id
        ),
        SmartAttendanceEvaluation,
        repo.organization_id,
    )
    ev = (await repo.session.execute(stmt)).scalar_one_or_none()
    if not ev:
        raise HTTPException(status_code=404, detail="Evaluation record not found")

    now = _utc_now()
    prev = ev.classification
    ev.classification = payload.classification
    if payload.attendance_rule_status:
        ev.attendance_rule_status = payload.attendance_rule_status
    elif payload.classification == "manually_verified_present":
        ev.attendance_rule_status = "full_attendance"
    elif payload.classification == "absent":
        ev.attendance_rule_status = "absent"

    ev.verified_by = payload.verified_by
    ev.verified_at = now
    ev.reason = f"Manually Verified ({payload.verified_by}): {payload.reason}"

    if (
        payload.classification == "manually_verified_present"
        and ev.member_id
        and ev.person_id
        and ev.group_id
    ):
        repo.session.add(
            AttendanceRecord(
                id=ulid.ulid(),
                person_id=ev.person_id,
                member_id=ev.member_id,
                group_id=ev.group_id,
                timestamp=now,
                confidence=1.0,
                location="Manual Faculty Verification",
                device_id="manual_override",
                event_type="check_in",
                notes=ev.reason,
                is_manual=True,
                created_by=payload.verified_by,
                organization_id=repo.organization_id,
            )
        )

    repo.session.add(
        AuditLog(
            id=ulid.ulid(),
            action="SMART_EVALUATION_MANUAL_VERIFY",
            target_type="smart_attendance_evaluation",
            target_id=ev.id,
            details=json.dumps(
                {
                    "previous": prev,
                    "new": ev.classification,
                    "verified_by": payload.verified_by,
                    "reason": payload.reason,
                }
            ),
            organization_id=repo.organization_id,
        )
    )
    await repo.session.commit()
    return {"success": True, "classification": ev.classification}


@router.post("/manual-fallback")
async def submit_manual_fallback(
    payload: ManualFallbackRequest,
    repo: AttendanceRepository = Depends(get_repository),
):
    """Alternative faculty manual attendance fallback labeled 'Manually Verified'."""
    date_str = payload.date or _today_str()
    sched = None
    group_id = payload.group_id
    if payload.schedule_id:
        sched = (
            await repo.session.execute(
                select(AcademicSchedule).where(AcademicSchedule.id == payload.schedule_id)
            )
        ).scalar_one_or_none()
        if sched and not group_id:
            group_id = sched.group_id

    if not group_id and not sched:
        raise HTTPException(
            status_code=400, detail="Either schedule_id or group_id is required"
        )

    now = _utc_now()
    processed = 0
    for entry in payload.entries:
        member = await repo.get_member_by_id(entry.member_id)
        if not member:
            continue
        is_present = entry.status in ("present", "late_entry")
        classification = "manually_verified_present" if is_present else "absent"
        rule_status = (
            "late_entry"
            if entry.status == "late_entry"
            else ("full_attendance" if is_present else "absent")
        )
        ev, _ = await SmartAttendanceEngine.upsert_smart_evaluation(
            repo.session,
            schedule_id=sched.id if sched else None,
            group_id=group_id,
            camera_id=sched.camera_id if sched else None,
            date_str=date_str,
            member_id=member.id,
            person_id=member.person_id,
            tracking_id=None,
            expected_section=sched.section if sched else None,
            detected_section=sched.section if sched else None,
            classification=classification,
            attendance_rule_status=rule_status,
            recognition_confidence=1.0 if is_present else 0.0,
            image_quality_score=1.0,
            face_visibility_score=1.0,
            temporal_consistency_score=1.0,
            head_pose_ok=True,
            duplicate_flagged=False,
            first_seen_at=now,
            last_seen_at=now,
            estimated_duration_minutes=0.0,
            observations_count=1,
            reason=f"Manually Verified ({payload.verified_by}): {payload.reason}",
            organization_id=repo.organization_id,
        )
        ev.classification = classification
        ev.attendance_rule_status = rule_status
        ev.verified_by = payload.verified_by
        ev.verified_at = now
        ev.reason = f"Manually Verified ({payload.verified_by}): {payload.reason}"

        if is_present and group_id:
            repo.session.add(
                AttendanceRecord(
                    id=ulid.ulid(),
                    person_id=member.person_id,
                    member_id=member.id,
                    group_id=group_id,
                    timestamp=now,
                    confidence=1.0,
                    location=sched.classroom if sched else "Manual Fallback",
                    device_id="manual_fallback",
                    event_type="check_in",
                    notes=f"Manually Verified: {payload.reason}",
                    is_manual=True,
                    created_by=payload.verified_by,
                    organization_id=repo.organization_id,
                )
            )
        processed += 1

    repo.session.add(
        AuditLog(
            id=ulid.ulid(),
            action="MANUAL_ATTENDANCE_FALLBACK_SUBMITTED",
            target_type="academic_schedule" if sched else "attendance_group",
            target_id=sched.id if sched else group_id,
            details=json.dumps(
                {
                    "date": date_str,
                    "verified_by": payload.verified_by,
                    "reason": payload.reason,
                    "count": processed,
                }
            ),
            organization_id=repo.organization_id,
        )
    )
    await repo.session.commit()
    return {"success": True, "processed": processed, "label": "Manually Verified"}


@router.post("/schedules/{schedule_id}/finalize")
async def finalize_schedule(
    schedule_id: str,
    payload: FinalizeScheduleRequest = FinalizeScheduleRequest(),
    repo: AttendanceRepository = Depends(get_repository),
):
    sched = (
        await repo.session.execute(
            _org_filter(
                select(AcademicSchedule).where(AcademicSchedule.id == schedule_id),
                AcademicSchedule,
                repo.organization_id,
            )
        )
    ).scalar_one_or_none()
    if not sched:
        raise HTTPException(status_code=404, detail="Schedule not found")

    result = await SmartAttendanceEngine.finalize_schedule_attendance(
        repo.session,
        schedule=sched,
        date_str=payload.date or _today_str(),
        verified_by=payload.verified_by,
        organization_id=repo.organization_id,
    )
    await repo.session.commit()
    return result


# ---------------------------------------------------------------------------
# 7. HOD Departmental Analytics, Student Self-View & Privacy Audit Log
# ---------------------------------------------------------------------------


@router.get("/hod/department-report")
async def get_hod_department_report(
    department: Optional[str] = None,
    section: Optional[str] = None,
    date: Optional[str] = None,
    repo: AttendanceRepository = Depends(get_repository),
):
    date_str = date or _today_str()
    s_stmt = _org_filter(
        select(AcademicSchedule).where(AcademicSchedule.is_active.is_(True)),
        AcademicSchedule,
        repo.organization_id,
    )
    if department:
        s_stmt = s_stmt.where(AcademicSchedule.department == department)
    if section:
        s_stmt = s_stmt.where(AcademicSchedule.section == section)
    schedules = (await repo.session.execute(s_stmt)).scalars().all()

    e_stmt = _org_filter(
        select(SmartAttendanceEvaluation).where(
            SmartAttendanceEvaluation.date == date_str
        ),
        SmartAttendanceEvaluation,
        repo.organization_id,
    )
    all_evals = (await repo.session.execute(e_stmt)).scalars().all()
    evals_by_sched: Dict[str, List[SmartAttendanceEvaluation]] = {}
    for ev in all_evals:
        if ev.schedule_id:
            evals_by_sched.setdefault(ev.schedule_id, []).append(ev)

    section_summaries = []
    totals = {
        "total_classes": len(schedules),
        "cctv_verified": 0,
        "manually_verified": 0,
        "pending_verification": 0,
        "absent": 0,
        "section_mismatch": 0,
        "late_or_partial": 0,
    }

    for sched in schedules:
        ev_list = evals_by_sched.get(sched.id, [])
        cctv_cnt = sum(1 for e in ev_list if e.classification == "cctv_verified_present")
        manual_cnt = sum(
            1 for e in ev_list if e.classification == "manually_verified_present"
        )
        pending_cnt = sum(1 for e in ev_list if e.classification == "pending_verification")
        absent_cnt = sum(1 for e in ev_list if e.classification == "absent")
        mismatch_cnt = sum(1 for e in ev_list if e.classification == "section_mismatch")
        late_partial_cnt = sum(
            1
            for e in ev_list
            if e.attendance_rule_status
            in ("late_entry", "early_departure", "partial_attendance")
        )
        headcount = await SmartAttendanceEngine.compute_headcount_reconciliation(
            repo.session,
            group_id=sched.group_id,
            schedule_id=sched.id,
            date_str=date_str,
            organization_id=repo.organization_id,
        )
        enrolled = max(1, headcount["enrolled"]) if headcount["enrolled"] else max(1, len(ev_list))
        attendance_pct = round(((cctv_cnt + manual_cnt) / enrolled) * 100.0, 1)

        totals["cctv_verified"] += cctv_cnt
        totals["manually_verified"] += manual_cnt
        totals["pending_verification"] += pending_cnt
        totals["absent"] += absent_cnt
        totals["section_mismatch"] += mismatch_cnt
        totals["late_or_partial"] += late_partial_cnt

        section_summaries.append(
            {
                "schedule_id": sched.id,
                "department": sched.department,
                "semester": sched.semester,
                "section": sched.section,
                "subject_code": sched.subject_code,
                "subject_name": sched.subject_name,
                "faculty_name": sched.faculty_name,
                "classroom": sched.classroom,
                "enrolled": headcount["enrolled"],
                "cctv_verified": cctv_cnt,
                "manually_verified": manual_cnt,
                "pending_verification": pending_cnt,
                "absent": absent_cnt,
                "section_mismatch": mismatch_cnt,
                "late_or_partial": late_partial_cnt,
                "attendance_percentage": attendance_pct,
            }
        )

    return {"date": date_str, "totals": totals, "sections": section_summaries}


@router.get("/student/{member_id}/attendance")
async def get_student_self_attendance(
    member_id: str,
    repo: AttendanceRepository = Depends(get_repository),
):
    """Privacy-isolated student view: returns strictly this single student's verified records."""
    member = await repo.get_member_by_id(member_id)
    if not member or member.organization_id != repo.organization_id:
        raise HTTPException(status_code=404, detail="Student not found")

    prof = (
        await repo.session.execute(
            select(StudentAcademicProfile).where(
                StudentAcademicProfile.member_id == member.id
            )
        )
    ).scalar_one_or_none()

    evals = (
        await repo.session.execute(
            select(SmartAttendanceEvaluation)
            .where(
                SmartAttendanceEvaluation.member_id == member.id,
                SmartAttendanceEvaluation.organization_id == repo.organization_id
                if repo.organization_id is not None
                else SmartAttendanceEvaluation.organization_id.is_(None),
            )
            .order_by(SmartAttendanceEvaluation.date.desc())
            .limit(100)
        )
    ).scalars().all()

    sched_ids = [e.schedule_id for e in evals if e.schedule_id]
    sched_map: Dict[str, AcademicSchedule] = {}
    if sched_ids:
        s_rows = (
            await repo.session.execute(
                select(AcademicSchedule).where(AcademicSchedule.id.in_(sched_ids))
            )
        ).scalars().all()
        sched_map = {s.id: s for s in s_rows}

    present_count = sum(
        1
        for e in evals
        if e.classification in ("cctv_verified_present", "manually_verified_present")
    )
    pending_count = sum(1 for e in evals if e.classification == "pending_verification")
    absent_count = sum(1 for e in evals if e.classification == "absent")

    return {
        "student": {
            "member_id": member.id,
            "name": member.name,
            "registration_number": prof.registration_number if prof else None,
            "department": prof.department if prof else None,
            "semester": prof.semester if prof else None,
            "section": prof.section if prof else None,
            "biometric_consent_granted": (
                prof.biometric_consent_granted if prof else True
            ),
            "non_biometric_opt_out": prof.non_biometric_opt_out if prof else False,
        },
        "summary": {
            "total_classes_recorded": len(evals),
            "present": present_count,
            "pending_verification": pending_count,
            "absent": absent_count,
            "attendance_percentage": (
                round((present_count / len(evals)) * 100.0, 1) if evals else 0.0
            ),
        },
        "records": [
            {
                "id": e.id,
                "date": e.date,
                "subject": (
                    f"{sched_map[e.schedule_id].subject_code} - {sched_map[e.schedule_id].subject_name}"
                    if e.schedule_id in sched_map
                    else "General Session"
                ),
                "classroom": (
                    sched_map[e.schedule_id].classroom
                    if e.schedule_id in sched_map
                    else None
                ),
                "verification_source": (
                    "Manually Verified"
                    if e.classification == "manually_verified_present"
                    else (
                        "CCTV Verified"
                        if e.classification == "cctv_verified_present"
                        else e.classification
                    )
                ),
                "classification": e.classification,
                "attendance_rule_status": e.attendance_rule_status,
                "estimated_duration_minutes": round(
                    float(e.estimated_duration_minutes), 1
                ),
                "first_seen_at": (
                    e.first_seen_at.isoformat() if e.first_seen_at else None
                ),
                "last_seen_at": e.last_seen_at.isoformat() if e.last_seen_at else None,
                "reason": e.reason,
            }
            for e in evals
        ],
    }


@router.get("/audit-logs")
async def list_cctv_audit_logs(
    limit: int = Query(default=100, ge=1, le=500),
    repo: AttendanceRepository = Depends(get_repository),
):
    stmt = _org_filter(select(AuditLog), AuditLog, repo.organization_id).order_by(
        AuditLog.timestamp.desc()
    )
    rows = (await repo.session.execute(stmt.limit(limit))).scalars().all()
    return [
        {
            "id": a.id,
            "timestamp": a.timestamp.isoformat() if a.timestamp else None,
            "action": a.action,
            "target_type": a.target_type,
            "target_id": a.target_id,
            "details": a.details,
        }
        for a in rows
    ]


class IpStreamProbeRequest(BaseModel):
    url: str


@router.post("/ip-stream/probe")
async def probe_mobile_ip_stream(payload: IpStreamProbeRequest):
    try:
        return await probe_ip_stream(payload.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/ip-stream/mjpeg")
async def stream_mobile_ip_mjpeg(
    request: Request,
    url: str = Query(..., min_length=3),
):
    try:
        resolved = validate_ip_stream_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return StreamingResponse(
        iter_mjpeg_frames(resolved, request.is_disconnected),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Access-Control-Allow-Origin": "*",
        },
    )


@router.get("/ip-stream/diagnostics")
async def get_mobile_ip_diagnostics(
    url: str = Query(..., min_length=3),
):
    try:
        return CameraStreamRegistry.get_diagnostics(url)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class IpStreamReconnectRequest(BaseModel):
    url: str


@router.post("/ip-stream/reconnect")
async def reconnect_mobile_ip_stream(payload: IpStreamReconnectRequest):
    try:
        return CameraStreamRegistry.reconnect_stream(payload.url)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc



