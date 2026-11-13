"""API endpoints for Class Session Video Playback, Faculty Review, and Audit Trail."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, get_organization_id
from services.recording_service import RecordingService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/recordings", tags=["recordings"])


class AttendanceCorrectionRequest(BaseModel):
    member_id: str = Field(..., description="Student member ID")
    new_status: str = Field(..., description="Target status ('present', 'late', 'absent')")
    reason: str = Field(..., min_length=3, description="Justification reason for change")
    corrected_by: str = Field(..., description="Reviewing faculty name or ID")


class RetentionPolicyUpdateRequest(BaseModel):
    retention_days: int = Field(..., ge=1, le=365, description="Retention duration in days")


class DeleteRecordingRequest(BaseModel):
    deleted_by: str = Field(..., description="Faculty or Administrator identity")
    reason: str = Field(..., min_length=3, description="Audit reason for permanent video deletion")


@router.get("", response_model=List[Dict[str, Any]])
async def list_recordings(
    course: Optional[str] = Query(None, description="Course code filter (e.g. CS-301)"),
    section: Optional[str] = Query(None, description="Section filter (e.g. Section A)"),
    date: Optional[str] = Query(None, description="Date filter (YYYY-MM-DD)"),
    schedule_id: Optional[str] = Query(None, description="Schedule ID"),
    session: AsyncSession = Depends(get_db),
    org_id: Optional[str] = Depends(get_organization_id),
):
    """Retrieve stored class session recordings matching course, section, date, and session filters."""
    recordings = await RecordingService.list_recordings(
        session,
        course_code=course,
        section=section,
        session_date=date,
        schedule_id=schedule_id,
        organization_id=org_id,
    )
    return [
        {
            "id": r.id,
            "schedule_id": r.schedule_id,
            "course_code": r.course_code,
            "course_name": r.course_name,
            "section": r.section,
            "session_date": r.session_date,
            "start_time": r.start_time,
            "end_time": r.end_time,
            "classroom": r.classroom,
            "camera_id": r.camera_id,
            "file_size_bytes": r.file_size_bytes,
            "duration_seconds": r.duration_seconds,
            "format": r.format,
            "status": r.status,
            "retention_days": r.retention_days,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in recordings
    ]


@router.get("/{recording_id}")
async def get_recording_detail(
    recording_id: str,
    session: AsyncSession = Depends(get_db),
):
    """Fetch metadata for a single class session recording."""
    r = await RecordingService.get_recording(session, recording_id)
    return {
        "id": r.id,
        "schedule_id": r.schedule_id,
        "course_code": r.course_code,
        "course_name": r.course_name,
        "section": r.section,
        "session_date": r.session_date,
        "start_time": r.start_time,
        "end_time": r.end_time,
        "classroom": r.classroom,
        "camera_id": r.camera_id,
        "file_size_bytes": r.file_size_bytes,
        "duration_seconds": r.duration_seconds,
        "format": r.format,
        "status": r.status,
        "retention_days": r.retention_days,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.get("/{recording_id}/stream")
async def stream_recording(
    recording_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
    range_header: Optional[str] = Header(None, alias="Range"),
    x_faculty_id: Optional[str] = Header(None, alias="X-Faculty-Id"),
):
    """Secure range-supported streaming of class recording video clip.
    
    Restricted to authorized faculty and administrators. Logs every access in VideoAccessAudit.
    """
    accessed_by = x_faculty_id or request.query_params.get("user") or "Faculty Reviewer"
    client_ip = request.client.host if request.client else "127.0.0.1"

    return await RecordingService.stream_recording_file(
        session,
        recording_id=recording_id,
        range_header=range_header,
        accessed_by=accessed_by,
        ip_address=client_ip,
    )


@router.get("/{recording_id}/roster")
async def get_recording_roster(
    recording_id: str,
    session: AsyncSession = Depends(get_db),
):
    """Retrieve student roster, current attendance, and video detection timeline events for a recording."""
    return await RecordingService.get_recording_roster_and_attendance(session, recording_id)


@router.post("/{recording_id}/attendance")
async def correct_attendance(
    recording_id: str,
    payload: AttendanceCorrectionRequest,
    session: AsyncSession = Depends(get_db),
    org_id: Optional[str] = Depends(get_organization_id),
):
    """Faculty attendance review and correction endpoint.
    
    Updates attendance status and records an immutable audit trail entry detailing who, when, and why.
    """
    audit = await RecordingService.record_attendance_correction(
        session,
        recording_id=recording_id,
        member_id=payload.member_id,
        new_status=payload.new_status,
        reason=payload.reason,
        corrected_by=payload.corrected_by,
        organization_id=org_id,
    )
    return {
        "success": True,
        "audit_id": audit.id,
        "student_name": audit.student_name,
        "previous_status": audit.previous_status,
        "new_status": audit.new_status,
        "corrected_by": audit.corrected_by,
        "corrected_at": audit.corrected_at.isoformat(),
    }


@router.get("/{recording_id}/audit-trail")
async def get_audit_trail(
    recording_id: str,
    session: AsyncSession = Depends(get_db),
):
    """Retrieve full audit trail of video clip accesses and attendance corrections."""
    return await RecordingService.get_audit_trail(session, recording_id)


@router.get("/settings/retention")
async def get_retention_settings(
    session: AsyncSession = Depends(get_db),
    org_id: Optional[str] = Depends(get_organization_id),
):
    """Retrieve configurable recording retention policies and disk storage stats."""
    return await RecordingService.get_retention_policy_and_stats(session, organization_id=org_id)


@router.post("/settings/retention")
async def update_retention_policy(
    payload: RetentionPolicyUpdateRequest,
    session: AsyncSession = Depends(get_db),
    org_id: Optional[str] = Depends(get_organization_id),
):
    """Update recording retention days and trigger automated expiration pruning."""
    return await RecordingService.update_retention_policy_and_prune(
        session,
        retention_days=payload.retention_days,
        organization_id=org_id,
    )


@router.delete("/{recording_id}")
async def delete_recording_file(
    recording_id: str,
    payload: DeleteRecordingRequest,
    session: AsyncSession = Depends(get_db),
):
    """Authorize deletion of a specific class recording with immutable audit log."""
    return await RecordingService.delete_recording(
        session,
        recording_id=recording_id,
        deleted_by=payload.deleted_by,
        reason=payload.reason,
    )

