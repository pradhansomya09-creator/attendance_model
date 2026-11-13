"""Centralized Smart Attendance Confidence, Temporal Consistency, Section Validation & Recovery Engine."""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
import ulid
from sqlalchemy import and_, or_, select

from core.cipher import decrypt_local_data, encrypt_local_data
from core.vision.head_pose import HeadPoseEstimate
from core.vision.image_quality import ImageQualityReport
from database.models import (
    AcademicSchedule,
    AttendanceGroup,
    AttendanceMember,
    AttendanceRecord,
    AttendanceSession,
    AuditLog,
    CctvCamera,
    CrossSectionException,
    Face,
    SectionMismatchAlert,
    SmartAttendanceEvaluation,
    StudentAcademicProfile,
    UnknownStudentDetection,
)
from time_utils import local_now

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _today_str() -> str:
    return local_now().strftime("%Y-%m-%d")


@dataclass
class TrackObservationState:
    """In-memory multi-frame evidence accumulator for an active tracked face."""

    track_id: int
    first_seen_at: datetime
    last_seen_at: datetime
    observations_count: int = 0
    candidate_votes: Dict[str, List[float]] = field(default_factory=dict)
    quality_scores: List[float] = field(default_factory=list)
    visibility_scores: List[float] = field(default_factory=list)
    clarity_scores: List[float] = field(default_factory=list)
    pose_ok_frames: int = 0
    best_crop_bytes: Optional[bytes] = None
    best_crop_clarity: float = -1.0
    best_face_dict: Optional[Dict[str, Any]] = None
    confirmed_person_id: Optional[str] = None
    duplicate_conflict_flagged: bool = False
    unknown_logged: bool = False
    mismatch_logged: bool = False
    last_persisted_at: float = 0.0

    def record_observation(
        self,
        *,
        now: datetime,
        quality_score: float,
        pose: HeadPoseEstimate,
        person_id: Optional[str],
        similarity: float,
        crop_bytes: Optional[bytes],
        face_dict: Optional[Dict[str, Any]],
    ) -> None:
        self.last_seen_at = now
        self.observations_count += 1
        self.quality_scores.append(float(quality_score))
        self.visibility_scores.append(float(pose.visibility_score))
        self.clarity_scores.append(float(pose.clarity_score))
        if pose.pose_ok:
            self.pose_ok_frames += 1

        if person_id:
            votes = self.candidate_votes.setdefault(person_id, [])
            votes.append(float(similarity))
            if (
                self.confirmed_person_id
                and self.confirmed_person_id != person_id
                and len(votes) >= 2
            ):
                self.duplicate_conflict_flagged = True

        if crop_bytes is not None and pose.clarity_score > self.best_crop_clarity:
            self.best_crop_clarity = pose.clarity_score
            self.best_crop_bytes = crop_bytes
            self.best_face_dict = face_dict

    def summary(self) -> Tuple[Optional[str], float, float]:
        """Return (best_person_id, mean_similarity, temporal_consistency_score)."""
        if not self.candidate_votes:
            return None, 0.0, 0.0

        best_pid = max(
            self.candidate_votes,
            key=lambda pid: (len(self.candidate_votes[pid]), sum(self.candidate_votes[pid])),
        )
        sims = self.candidate_votes[best_pid]
        mean_sim = float(sum(sims) / len(sims))
        consistency = float(len(sims) / max(1, self.observations_count))
        return best_pid, mean_sim, consistency


@dataclass
class SmartSessionAccumulator:
    """Tracks all active faces and headcount metrics for a live streaming session."""

    tracks: Dict[int, TrackObservationState] = field(default_factory=dict)
    unique_track_ids: set[int] = field(default_factory=set)
    confirmed_person_ids: set[str] = field(default_factory=set)
    unknown_track_ids: set[int] = field(default_factory=set)
    pending_track_ids: set[int] = field(default_factory=set)
    mismatch_person_ids: set[str] = field(default_factory=set)
    duplicate_alerts: int = 0


def _encode_face_crop(image: np.ndarray, bbox: Dict[str, Any]) -> Optional[bytes]:
    if image is None or image.size == 0 or not bbox:
        return None
    h, w = image.shape[:2]
    x = max(0, int(bbox.get("x", 0)) - 12)
    y = max(0, int(bbox.get("y", 0)) - 12)
    x2 = min(w, int(bbox.get("x", 0) + bbox.get("width", 0)) + 12)
    y2 = min(h, int(bbox.get("y", 0) + bbox.get("height", 0)) + 12)
    if x2 <= x or y2 <= y:
        return None
    crop = image[y:y2, x:x2]
    ok, buf = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    return bytes(buf) if ok else None


def _parse_hhmm_minutes(hhmm: Optional[str]) -> Optional[int]:
    if not hhmm or ":" not in hhmm:
        return None
    try:
        hh, mm = hhmm.split(":", 1)
        return int(hh) * 60 + int(mm)
    except ValueError:
        return None


class SmartAttendanceEngine:
    """Centralized validation, section checking, unknown queueing, and headcount reconciliation."""

    MIN_TEMPORAL_OBSERVATIONS = 2
    MIN_TEMPORAL_CONSISTENCY = 0.55
    MIN_RECOGNITION_CONFIDENCE = 0.36
    MIN_IMAGE_QUALITY_FOR_CONFIRM = 0.38

    @staticmethod
    async def find_active_schedule(
        session,
        *,
        group_id: Optional[str],
        camera_id: Optional[str] = None,
        organization_id: Optional[str] = None,
    ) -> Optional[AcademicSchedule]:
        stmt = select(AcademicSchedule).where(AcademicSchedule.is_active.is_(True))
        if organization_id is not None:
            stmt = stmt.where(AcademicSchedule.organization_id == organization_id)
        else:
            stmt = stmt.where(AcademicSchedule.organization_id.is_(None))

        if camera_id and group_id and group_id != "all":
            stmt = stmt.where(
                or_(
                    AcademicSchedule.camera_id == camera_id,
                    AcademicSchedule.group_id == group_id,
                )
            )
        elif camera_id:
            stmt = stmt.where(AcademicSchedule.camera_id == camera_id)
        elif group_id and group_id != "all":
            stmt = stmt.where(AcademicSchedule.group_id == group_id)
        else:
            return None

        res = await session.execute(stmt)
        schedules = res.scalars().all()
        if not schedules:
            return None

        now_local = local_now()
        weekday_str = str(now_local.weekday())
        now_mins = now_local.hour * 60 + now_local.minute

        # Prefer schedule matching today's day & current class window
        for sched in schedules:
            if sched.day_of_week not in ("*", weekday_str):
                continue
            start_m = _parse_hhmm_minutes(sched.start_time)
            end_m = _parse_hhmm_minutes(sched.end_time)
            if start_m is not None and end_m is not None:
                if (start_m - 20) <= now_mins <= (end_m + 20):
                    return sched
        return schedules[0]

    @staticmethod
    def evaluate_entry_exit_rule(
        *,
        first_seen_at: datetime,
        last_seen_at: datetime,
        schedule: Optional[AcademicSchedule],
        group: Optional[AttendanceGroup],
        classification: str,
    ) -> Tuple[str, float]:
        """Determine attendance rule status and duration from entry/exit timestamps."""
        duration_minutes = max(
            0.0, (last_seen_at - first_seen_at).total_seconds() / 60.0
        )
        if classification == "pending_verification":
            return "pending_verification", duration_minutes
        if classification == "absent":
            return "absent", duration_minutes
        if classification not in ("cctv_verified_present", "manually_verified_present"):
            return "pending_verification", duration_minutes

        start_str = (
            schedule.start_time
            if schedule is not None
            else (group.class_start_time if group is not None else None)
        )
        end_str = (
            schedule.end_time
            if schedule is not None
            else (group.class_end_time if group is not None else None)
        )
        late_limit = (
            schedule.late_after_minutes
            if schedule is not None
            else int((group.late_threshold_minutes if group else None) or 15)
        )
        early_limit = schedule.early_exit_minutes if schedule is not None else 10
        min_pct = schedule.min_presence_percent if schedule is not None else 60.0

        start_m = _parse_hhmm_minutes(start_str)
        end_m = _parse_hhmm_minutes(end_str)
        first_m = first_seen_at.hour * 60 + first_seen_at.minute
        last_m = last_seen_at.hour * 60 + last_seen_at.minute

        is_late = start_m is not None and (first_m - start_m) > late_limit
        is_early = (
            end_m is not None
            and duration_minutes >= 1.0
            and (end_m - last_m) > early_limit
        )

        if start_m is not None and end_m is not None and end_m > start_m:
            class_len = float(end_m - start_m)
            # Only enforce partial attendance once observations span >1 min or at finalization
            if duration_minutes >= 1.0 and (duration_minutes / class_len) * 100.0 < min_pct:
                if is_late:
                    return "late_entry", duration_minutes
                if is_early:
                    return "early_departure", duration_minutes
                return "partial_attendance", duration_minutes

        if is_late and is_early:
            return "partial_attendance", duration_minutes
        if is_late:
            return "late_entry", duration_minutes
        if is_early:
            return "early_departure", duration_minutes
        return "full_attendance", duration_minutes

    @classmethod
    def compute_centralized_classification(
        cls,
        *,
        recognition_confidence: float,
        image_quality: ImageQualityReport,
        visibility_score: float,
        temporal_consistency: float,
        observations_count: int,
        pose_ok: bool,
        is_registered: bool,
        section_matched: bool,
        has_exception: bool,
        camera_online: bool,
        duplicate_flagged: bool,
        non_biometric_opt_out: bool,
    ) -> Tuple[str, str]:
        """Evaluate all 10 factors before emitting final classification & reason."""
        if not camera_online:
            return "pending_verification", "Camera offline or unstable; manual verification required."
        if image_quality.status == "red" or image_quality.score < cls.MIN_IMAGE_QUALITY_FOR_CONFIRM:
            return (
                "pending_verification",
                "Image quality below recognition threshold: "
                + ", ".join(image_quality.issues or ["poor_visibility"]),
            )
        if non_biometric_opt_out:
            return "pending_verification", "Student opted for non-biometric verification."
        if not is_registered:
            return "unknown_student", "Unregistered face detected; identity verification required."
        if not section_matched and not has_exception:
            return "section_mismatch", "Detected student belongs to another academic section."
        if duplicate_flagged:
            return "pending_verification", "Conflicting identity/duplicate track flagged for review."
        if not pose_ok or visibility_score < 0.35:
            return "pending_verification", "Face rotated or partially occluded; awaiting clearer frame."
        if observations_count < cls.MIN_TEMPORAL_OBSERVATIONS:
            return "pending_verification", "Accumulating multi-frame temporal observations."
        if (
            recognition_confidence < cls.MIN_RECOGNITION_CONFIDENCE
            or temporal_consistency < cls.MIN_TEMPORAL_CONSISTENCY
        ):
            return (
                "pending_verification",
                "Low recognition confidence or inconsistent temporal identity match.",
            )
        return "cctv_verified_present", "All biometric, quality, temporal, and section checks passed."

    @classmethod
    async def validate_member_for_schedule(
        cls,
        session,
        *,
        member: AttendanceMember,
        schedule: Optional[AcademicSchedule],
        date_str: str,
        organization_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validate student profile, consent/opt-out, section match, and approved exceptions."""
        res = await session.execute(
            select(StudentAcademicProfile).where(
                StudentAcademicProfile.member_id == member.id
            )
        )
        profile = res.scalar_one_or_none()

        non_biometric_opt_out = bool(
            profile and (profile.non_biometric_opt_out or not profile.biometric_consent_granted)
        )
        if schedule is None or profile is None:
            return {
                "profile": profile,
                "section_matched": True,
                "has_exception": False,
                "expected_section": schedule.section if schedule else None,
                "detected_section": profile.section if profile else None,
                "non_biometric_opt_out": non_biometric_opt_out,
            }

        section_matched = (
            profile.section.strip().lower() == schedule.section.strip().lower()
            and profile.department.strip().lower() == schedule.department.strip().lower()
            and profile.semester.strip().lower() == schedule.semester.strip().lower()
        )
        has_exception = False
        if not section_matched:
            exc_res = await session.execute(
                select(CrossSectionException).where(
                    CrossSectionException.member_id == member.id,
                    CrossSectionException.target_schedule_id == schedule.id,
                    CrossSectionException.valid_date == date_str,
                    CrossSectionException.status == "approved",
                )
            )
            has_exception = exc_res.scalar_one_or_none() is not None

        return {
            "profile": profile,
            "section_matched": section_matched,
            "has_exception": has_exception,
            "expected_section": schedule.section,
            "detected_section": profile.section,
            "non_biometric_opt_out": non_biometric_opt_out,
        }

    @classmethod
    async def record_section_mismatch(
        cls,
        session,
        *,
        member: AttendanceMember,
        profile: StudentAcademicProfile,
        schedule: AcademicSchedule,
        camera_id: Optional[str],
        organization_id: Optional[str],
    ) -> SectionMismatchAlert:
        # Deduplicate open alert for same member + schedule today
        res = await session.execute(
            select(SectionMismatchAlert).where(
                SectionMismatchAlert.member_id == member.id,
                SectionMismatchAlert.schedule_id == schedule.id,
                SectionMismatchAlert.status == "open",
            )
        )
        existing = res.scalar_one_or_none()
        if existing is not None:
            return existing

        alert = SectionMismatchAlert(
            id=ulid.ulid(),
            member_id=member.id,
            person_id=member.person_id,
            student_name=member.name,
            registration_number=profile.registration_number,
            actual_section=f"{profile.department} Sem {profile.semester} - {profile.section}",
            scheduled_section=f"{schedule.department} Sem {schedule.semester} - {schedule.section}",
            schedule_id=schedule.id,
            camera_id=camera_id,
            classroom=schedule.classroom,
            detected_at=_utc_now(),
            status="open",
            organization_id=organization_id,
        )
        session.add(alert)
        return alert

    @classmethod
    async def record_unknown_student_detection(
        cls,
        session,
        *,
        tracking_id: str,
        camera_id: Optional[str],
        schedule_id: Optional[str],
        group_id: Optional[str],
        classroom: Optional[str],
        crop_bytes: Optional[bytes],
        embedding: Optional[np.ndarray],
        confidence_best_guess: float,
        organization_id: Optional[str],
    ) -> UnknownStudentDetection:
        enc_snapshot = encrypt_local_data(crop_bytes) if crop_bytes else None
        enc_emb = (
            encrypt_local_data(embedding.astype(np.float32).tobytes())
            if embedding is not None
            else None
        )
        record = UnknownStudentDetection(
            id=ulid.ulid(),
            tracking_id=tracking_id,
            camera_id=camera_id,
            schedule_id=schedule_id,
            group_id=group_id,
            classroom=classroom,
            detected_at=_utc_now(),
            frame_snapshot_enc=enc_snapshot,
            embedding_enc=enc_emb,
            confidence_best_guess=float(confidence_best_guess),
            status="pending",
            organization_id=organization_id,
        )
        session.add(record)
        session.add(
            AuditLog(
                id=ulid.ulid(),
                action="UNKNOWN_STUDENT_DETECTED",
                target_type="unknown_student_detection",
                target_id=record.id,
                details=json.dumps(
                    {
                        "tracking_id": tracking_id,
                        "camera_id": camera_id,
                        "classroom": classroom,
                        "schedule_id": schedule_id,
                    }
                ),
                organization_id=organization_id,
            )
        )
        return record

    @classmethod
    async def upsert_smart_evaluation(
        cls,
        session,
        *,
        schedule_id: Optional[str],
        group_id: Optional[str],
        camera_id: Optional[str],
        date_str: str,
        member_id: Optional[str],
        person_id: Optional[str],
        tracking_id: Optional[str],
        expected_section: Optional[str],
        detected_section: Optional[str],
        classification: str,
        attendance_rule_status: str,
        recognition_confidence: float,
        image_quality_score: float,
        face_visibility_score: float,
        temporal_consistency_score: float,
        head_pose_ok: bool,
        duplicate_flagged: bool,
        first_seen_at: datetime,
        last_seen_at: datetime,
        estimated_duration_minutes: float,
        observations_count: int,
        reason: str,
        organization_id: Optional[str],
    ) -> Tuple[SmartAttendanceEvaluation, bool]:
        """Create or update a deduplicated smart evaluation (one record per student per class/date)."""
        stmt = select(SmartAttendanceEvaluation).where(
            SmartAttendanceEvaluation.date == date_str
        )
        if schedule_id:
            stmt = stmt.where(SmartAttendanceEvaluation.schedule_id == schedule_id)
        elif group_id:
            stmt = stmt.where(SmartAttendanceEvaluation.group_id == group_id)

        if member_id:
            stmt = stmt.where(SmartAttendanceEvaluation.member_id == member_id)
        elif tracking_id:
            stmt = stmt.where(SmartAttendanceEvaluation.tracking_id == tracking_id)

        res = await session.execute(stmt)
        existing = res.scalar_one_or_none()
        if existing is not None:
            # Never overwrite an explicit manual verification with an automated downgrade
            if existing.classification == "manually_verified_present":
                return existing, False

            # Detect duplicate track claiming already-verified member in same session
            if (
                existing.classification == "cctv_verified_present"
                and existing.tracking_id
                and tracking_id
                and existing.tracking_id != tracking_id
                and (last_seen_at - (existing.last_seen_at or last_seen_at)).total_seconds()
                < 5.0
            ):
                existing.duplicate_flagged = True
                duplicate_flagged = True

            if first_seen_at and (
                existing.first_seen_at is None or first_seen_at < existing.first_seen_at
            ):
                existing.first_seen_at = first_seen_at
            if last_seen_at and (
                existing.last_seen_at is None or last_seen_at > existing.last_seen_at
            ):
                existing.last_seen_at = last_seen_at

            if existing.first_seen_at and existing.last_seen_at:
                existing.estimated_duration_minutes = max(
                    existing.estimated_duration_minutes,
                    (existing.last_seen_at - existing.first_seen_at).total_seconds()
                    / 60.0,
                )

            existing.observations_count = max(
                existing.observations_count, observations_count
            )
            existing.recognition_confidence = max(
                existing.recognition_confidence, recognition_confidence
            )
            existing.image_quality_score = image_quality_score
            existing.face_visibility_score = max(
                existing.face_visibility_score, face_visibility_score
            )
            existing.temporal_consistency_score = max(
                existing.temporal_consistency_score, temporal_consistency_score
            )
            existing.head_pose_ok = head_pose_ok
            existing.duplicate_flagged = existing.duplicate_flagged or duplicate_flagged

            # Upgrade pending -> verified or section_mismatch, never downgrade verified -> pending
            if existing.classification != "cctv_verified_present":
                existing.classification = classification
                existing.attendance_rule_status = attendance_rule_status
                existing.reason = reason
            else:
                existing.attendance_rule_status = attendance_rule_status
            return existing, False

        row = SmartAttendanceEvaluation(
            id=ulid.ulid(),
            schedule_id=schedule_id,
            group_id=group_id,
            camera_id=camera_id,
            date=date_str,
            member_id=member_id,
            person_id=person_id,
            tracking_id=tracking_id,
            expected_section=expected_section,
            detected_section=detected_section,
            classification=classification,
            attendance_rule_status=attendance_rule_status,
            recognition_confidence=float(recognition_confidence),
            image_quality_score=float(image_quality_score),
            face_visibility_score=float(face_visibility_score),
            temporal_consistency_score=float(temporal_consistency_score),
            head_pose_ok=bool(head_pose_ok),
            duplicate_flagged=bool(duplicate_flagged),
            first_seen_at=first_seen_at,
            last_seen_at=last_seen_at,
            estimated_duration_minutes=float(estimated_duration_minutes),
            observations_count=int(observations_count),
            reason=reason,
            organization_id=organization_id,
        )
        session.add(row)
        return row, True

    @staticmethod
    async def compute_headcount_reconciliation(
        session,
        *,
        group_id: Optional[str],
        schedule_id: Optional[str],
        date_str: str,
        live_accumulator: Optional[SmartSessionAccumulator] = None,
        organization_id: Optional[str] = None,
    ) -> Dict[str, int]:
        """Build classroom headcount vs verified student identity reconciliation summary."""
        enrolled_count = 0
        if group_id and group_id != "all":
            m_stmt = select(AttendanceMember).where(
                AttendanceMember.group_id == group_id,
                AttendanceMember.is_active.is_(True),
                AttendanceMember.is_deleted.is_(False),
            )
            m_res = await session.execute(m_stmt)
            enrolled_count = len(m_res.scalars().all())
        elif schedule_id:
            s_res = await session.execute(
                select(AcademicSchedule).where(AcademicSchedule.id == schedule_id)
            )
            sched = s_res.scalar_one_or_none()
            if sched and sched.group_id:
                m_res = await session.execute(
                    select(AttendanceMember).where(
                        AttendanceMember.group_id == sched.group_id,
                        AttendanceMember.is_active.is_(True),
                        AttendanceMember.is_deleted.is_(False),
                    )
                )
                enrolled_count = len(m_res.scalars().all())

        e_stmt = select(SmartAttendanceEvaluation).where(
            SmartAttendanceEvaluation.date == date_str
        )
        if schedule_id:
            e_stmt = e_stmt.where(SmartAttendanceEvaluation.schedule_id == schedule_id)
        elif group_id and group_id != "all":
            e_stmt = e_stmt.where(SmartAttendanceEvaluation.group_id == group_id)
        if organization_id is not None:
            e_stmt = e_stmt.where(
                SmartAttendanceEvaluation.organization_id == organization_id
            )
        else:
            e_stmt = e_stmt.where(SmartAttendanceEvaluation.organization_id.is_(None))

        e_res = await session.execute(e_stmt)
        evals = e_res.scalars().all()

        confirmed_present = sum(
            1
            for e in evals
            if e.classification
            in ("cctv_verified_present", "manually_verified_present")
        )
        pending_verification = sum(
            1 for e in evals if e.classification == "pending_verification"
        )
        unknown_db = sum(1 for e in evals if e.classification == "unknown_student")
        section_mismatches = sum(
            1 for e in evals if e.classification == "section_mismatch"
        )
        duplicate_alerts = sum(1 for e in evals if e.duplicate_flagged)

        if live_accumulator is not None:
            unique_detected = max(
                len(live_accumulator.unique_track_ids),
                confirmed_present + unknown_db + pending_verification,
            )
            unknown_count = max(unknown_db, len(live_accumulator.unknown_track_ids))
            duplicate_alerts = max(duplicate_alerts, live_accumulator.duplicate_alerts)
        else:
            unique_detected = (
                confirmed_present + unknown_db + pending_verification + section_mismatches
            )
            unknown_count = unknown_db

        return {
            "enrolled": enrolled_count,
            "unique_detected": unique_detected,
            "successfully_identified": confirmed_present,
            "unknown_individuals": unknown_count,
            "pending_verification": pending_verification,
            "confirmed_present": confirmed_present,
            "section_mismatches": section_mismatches,
            "duplicate_alerts": duplicate_alerts,
        }

    @staticmethod
    def decrypt_snapshot_data_url(encrypted: Optional[bytes]) -> Optional[str]:
        if not encrypted:
            return None
        try:
            raw = decrypt_local_data(encrypted)
            return "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")
        except Exception:
            return None

    @classmethod
    async def reconcile_unknowns_for_newly_registered(
        cls,
        session,
        *,
        face_recognizer,
        organization_id: Optional[str] = None,
        similarity_threshold: float = 0.45,
    ) -> List[Dict[str, Any]]:
        """Check previously detected unknown students against newly registered facial profiles."""
        if face_recognizer is None:
            return []

        stmt = select(UnknownStudentDetection).where(
            UnknownStudentDetection.status == "pending",
            UnknownStudentDetection.embedding_enc.is_not(None),
        )
        if organization_id is not None:
            stmt = stmt.where(UnknownStudentDetection.organization_id == organization_id)
        else:
            stmt = stmt.where(UnknownStudentDetection.organization_id.is_(None))

        res = await session.execute(stmt)
        pending_unknowns = res.scalars().all()
        if not pending_unknowns:
            return []

        embeddings_map = await face_recognizer.export_embeddings(
            organization_id=organization_id
        )
        if not embeddings_map:
            return []

        person_ids = list(embeddings_map.keys())
        matrix = np.stack([embeddings_map[pid] for pid in person_ids])

        matches: List[Dict[str, Any]] = []
        for unk in pending_unknowns:
            try:
                raw_emb = decrypt_local_data(unk.embedding_enc)
                vec = np.frombuffer(raw_emb, dtype=np.float32)
                if vec.shape[0] != matrix.shape[1]:
                    continue
                norm = np.linalg.norm(vec)
                if norm > 0:
                    vec = vec / norm
                sims = matrix @ vec
                best_idx = int(np.argmax(sims))
                best_sim = float(sims[best_idx])
                if best_sim >= similarity_threshold:
                    matched_pid = person_ids[best_idx]
                    m_res = await session.execute(
                        select(AttendanceMember).where(
                            AttendanceMember.person_id == matched_pid,
                            AttendanceMember.is_deleted.is_(False),
                        )
                    )
                    member = m_res.scalar_one_or_none()
                    if member is not None:
                        unk.status = "verified"
                        unk.resolved_member_id = member.id
                        unk.resolved_by = "auto_reconcile"
                        unk.resolved_at = _utc_now()
                        unk.confidence_best_guess = best_sim
                        unk.notes = (
                            f"Matched retroactively against newly registered profile {member.name} "
                            f"({best_sim:.2f})."
                        )
                        matches.append(
                            {
                                "unknown_id": unk.id,
                                "member_id": member.id,
                                "member_name": member.name,
                                "similarity": round(best_sim, 3),
                            }
                        )
            except Exception as exc:
                logger.debug("Unknown reconciliation skipped for %s: %s", unk.id, exc)
        return matches

    @classmethod
    async def finalize_schedule_attendance(
        cls,
        session,
        *,
        schedule: AcademicSchedule,
        date_str: str,
        verified_by: str,
        organization_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run centralized finalization for a class: never auto-marks absent on offline/red camera."""
        camera = None
        if schedule.camera_id:
            c_res = await session.execute(
                select(CctvCamera).where(CctvCamera.id == schedule.camera_id)
            )
            camera = c_res.scalar_one_or_none()

        camera_blocked = bool(
            camera
            and (camera.status in ("offline", "recording_failed") or camera.quality_status == "red")
        )

        members: List[AttendanceMember] = []
        if schedule.group_id:
            m_res = await session.execute(
                select(AttendanceMember).where(
                    AttendanceMember.group_id == schedule.group_id,
                    AttendanceMember.is_active.is_(True),
                    AttendanceMember.is_deleted.is_(False),
                )
            )
            members = list(m_res.scalars().all())

        e_res = await session.execute(
            select(SmartAttendanceEvaluation).where(
                SmartAttendanceEvaluation.schedule_id == schedule.id,
                SmartAttendanceEvaluation.date == date_str,
            )
        )
        evals = list(e_res.scalars().all())
        eval_by_member = {e.member_id: e for e in evals if e.member_id}

        marked_absent = 0
        kept_pending = 0

        for member in members:
            ev = eval_by_member.get(member.id)
            if ev is not None:
                if ev.classification == "pending_verification":
                    kept_pending += 1
                continue

            # Never automatically mark students absent if the camera was offline or image quality was red
            classification = "pending_verification" if camera_blocked else "absent"
            rule_status = "pending_verification" if camera_blocked else "absent"
            reason = (
                "Camera offline or poor visibility during class window; manual verification required."
                if camera_blocked
                else "No reliable attendance evidence established within scheduled class window."
            )
            await cls.upsert_smart_evaluation(
                session,
                schedule_id=schedule.id,
                group_id=schedule.group_id,
                camera_id=schedule.camera_id,
                date_str=date_str,
                member_id=member.id,
                person_id=member.person_id,
                tracking_id=None,
                expected_section=schedule.section,
                detected_section=schedule.section,
                classification=classification,
                attendance_rule_status=rule_status,
                recognition_confidence=0.0,
                image_quality_score=camera.quality_score if camera else 1.0,
                face_visibility_score=0.0,
                temporal_consistency_score=0.0,
                head_pose_ok=False,
                duplicate_flagged=False,
                first_seen_at=_utc_now(),
                last_seen_at=_utc_now(),
                estimated_duration_minutes=0.0,
                observations_count=0,
                reason=reason,
                organization_id=organization_id,
            )
            if camera_blocked:
                kept_pending += 1
            else:
                marked_absent += 1

        session.add(
            AuditLog(
                id=ulid.ulid(),
                action="SMART_ATTENDANCE_FINALIZED",
                target_type="academic_schedule",
                target_id=schedule.id,
                details=json.dumps(
                    {
                        "date": date_str,
                        "verified_by": verified_by,
                        "camera_blocked": camera_blocked,
                        "marked_absent": marked_absent,
                        "kept_pending": kept_pending,
                    }
                ),
                organization_id=organization_id,
            )
        )
        return {
            "schedule_id": schedule.id,
            "date": date_str,
            "camera_blocked": camera_blocked,
            "marked_absent": marked_absent,
            "kept_pending": kept_pending,
        }

