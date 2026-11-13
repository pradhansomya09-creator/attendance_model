from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import (
    String,
    Boolean,
    Integer,
    Float,
    ForeignKey,
    DateTime,
    Text,
    func,
    Index,
    LargeBinary,
    text,
    event,
    inspect,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, Session
from sqlalchemy.ext.asyncio import AsyncAttrs

from config.models import FACE_DETECTOR_CONFIG


class Base(AsyncAttrs, DeclarativeBase):
    pass


class SyncMixin(AsyncAttrs):
    """
    Mixin to add synchronization metadata and multi-tenancy.
    """

    organization_id: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, index=True
    )
    remote_id: Mapped[Optional[str]] = mapped_column(
        "cloud_id", String, nullable=True, index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    last_modified_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class DirectorySyncState:
    # Cloud revision last observed, independent of the local edit counter (version).
    sync_revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    sync_dirty: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")


class AttendanceGroup(Base, SyncMixin, DirectorySyncState):
    __tablename__ = "attendance_groups"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    late_threshold_minutes: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    late_threshold_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Default to current time in HH:MM format
    class_start_time: Mapped[str] = mapped_column(
        String, default=lambda: datetime.now().strftime("%H:%M")
    )
    class_end_time: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    attendance_mode: Mapped[str] = mapped_column(
        String, default="attendance", server_default="attendance", nullable=False
    )
    track_checkout: Mapped[bool] = mapped_column(Boolean, default=False)
    min_checkout_delay_minutes: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, default=15
    )
    scan_behavior: Mapped[str] = mapped_column(
        String, default="automatic", server_default="automatic", nullable=False
    )

    members: Mapped[List["AttendanceMember"]] = relationship(back_populates="group")
    records: Mapped[List["AttendanceRecord"]] = relationship(back_populates="group")
    sessions: Mapped[List["AttendanceSession"]] = relationship(back_populates="group")
    rule_history: Mapped[List["AttendanceGroupRule"]] = relationship(
        back_populates="group", order_by="AttendanceGroupRule.effective_from"
    )

    @property
    def settings(self):
        return {
            "late_threshold_minutes": self.late_threshold_minutes,
            "late_threshold_enabled": self.late_threshold_enabled,
            "class_start_time": self.class_start_time,
            "class_end_time": self.class_end_time,
            "attendance_mode": self.attendance_mode,
            "track_checkout": self.track_checkout,
            "min_checkout_delay_minutes": (
                self.min_checkout_delay_minutes
                if self.min_checkout_delay_minutes is not None
                else 15
            ),
            "scan_behavior": self.scan_behavior,
        }


class AttendanceMember(Base, SyncMixin, DirectorySyncState):
    __tablename__ = "attendance_members"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    person_id: Mapped[str] = mapped_column(String, nullable=False)
    group_id: Mapped[str] = mapped_column(
        String, ForeignKey("attendance_groups.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )
    joined_at_utc: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    joined_at_timezone: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    joined_at_offset_seconds: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    group: Mapped["AttendanceGroup"] = relationship(back_populates="members")
    records: Mapped[List["AttendanceRecord"]] = relationship(back_populates="member")
    sessions: Mapped[List["AttendanceSession"]] = relationship(back_populates="member")

    __table_args__ = (
        Index("ix_member_group_id", "group_id"),
        Index(
            "ux_member_person_global",
            "person_id",
            unique=True,
            sqlite_where=text("organization_id IS NULL"),
        ),
        Index(
            "ux_member_person_org",
            "person_id",
            "organization_id",
            unique=True,
            sqlite_where=text("organization_id IS NOT NULL"),
        ),
    )


class AttendanceRecord(Base, SyncMixin):
    __tablename__ = "attendance_records"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    person_id: Mapped[str] = mapped_column(String, nullable=False)
    member_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("attendance_members.id"), nullable=True
    )
    group_id: Mapped[str] = mapped_column(
        String, ForeignKey("attendance_groups.id"), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # Nullable companions: legacy rows are deliberately not guessed/backfilled.
    timestamp_utc: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, index=True
    )
    timestamp_timezone: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    timestamp_offset_seconds: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    modified_at_utc: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    location: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    device_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    event_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_voided: Mapped[bool] = mapped_column(Boolean, default=False)
    voided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    voided_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    void_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    member: Mapped["AttendanceMember"] = relationship(back_populates="records")
    group: Mapped["AttendanceGroup"] = relationship(back_populates="records")

    __table_args__ = (
        Index("ix_record_group_id", "group_id"),
        Index("ix_record_person_id", "person_id"),
        Index("ix_record_member_id", "member_id"),
        Index("ix_record_timestamp", "timestamp"),
        Index("ix_record_group_timestamp", "group_id", "timestamp"),
        Index("ix_record_device_id", "device_id"),
    )


class AttendanceSession(Base, SyncMixin):
    __tablename__ = "attendance_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    person_id: Mapped[str] = mapped_column(String, nullable=False)
    is_manual_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    provenance_updated_at_utc: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    member_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("attendance_members.id"), nullable=True
    )
    group_id: Mapped[str] = mapped_column(
        String, ForeignKey("attendance_groups.id"), nullable=False
    )
    applied_rule_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("attendance_group_rules.id"), nullable=True
    )
    date: Mapped[str] = mapped_column(String, nullable=False)  # YYYY-MM-DD
    visit_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    check_in_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    check_out_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    check_in_time_utc: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    check_in_time_timezone: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    check_in_time_offset_seconds: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    check_out_time_utc: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    check_out_time_timezone: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )
    check_out_time_offset_seconds: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    modified_at_utc: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )
    total_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="absent")
    is_late: Mapped[bool] = mapped_column(Boolean, default=False)
    late_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    member: Mapped["AttendanceMember"] = relationship(back_populates="sessions")
    group: Mapped["AttendanceGroup"] = relationship(back_populates="sessions")
    applied_rule: Mapped[Optional["AttendanceGroupRule"]] = relationship()

    @property
    def applied_schedule(self):
        # Only serialize an eagerly loaded, matching historical rule. Never
        # substitute today's group settings or trigger async lazy loading.
        rule = self.__dict__.get("applied_rule")
        if (
            rule is None
            or rule.id != self.applied_rule_id
            or rule.group_id != self.group_id
            or rule.organization_id != self.organization_id
        ):
            return None
        mode = rule.attendance_mode
        if mode == "attendance" and rule.track_checkout:
            mode = "work_hours"
        return {
            "class_start_time": rule.class_start_time,
            "class_end_time": rule.class_end_time,
            "attendance_mode": mode,
            "scan_behavior": rule.scan_behavior or "automatic",
            "min_checkout_delay_minutes": rule.min_checkout_delay_minutes
            if rule.min_checkout_delay_minutes is not None
            else 15,
        }

    __table_args__ = (
        Index("ix_session_group_id", "group_id"),
        Index("ix_session_person_id", "person_id"),
        Index("ix_session_member_id", "member_id"),
        Index("ix_session_applied_rule_id", "applied_rule_id"),
        Index("ix_session_date", "date"),
        Index("ix_session_group_date", "group_id", "date"),
        Index(
            "ux_session_member_date_visit",
            "member_id",
            "date",
            "visit_number",
            unique=True,
        ),
    )


class AttendanceSessionDeletion(Base):
    """Durable sync tombstone for a retired derived session ID."""

    __tablename__ = "attendance_session_deletions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    organization_id: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, index=True
    )
    person_id: Mapped[str] = mapped_column(String, nullable=False)
    group_id: Mapped[str] = mapped_column(String, nullable=False)
    date: Mapped[str] = mapped_column(String, nullable=False)
    deleted_at_utc: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        index=True,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        server_default=func.current_timestamp(),
    )


class AttendanceGroupRule(Base, SyncMixin):
    __tablename__ = "attendance_group_rules"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    group_id: Mapped[str] = mapped_column(
        String, ForeignKey("attendance_groups.id"), nullable=False
    )
    effective_from: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    effective_from_utc: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    effective_from_timezone: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )
    effective_from_offset_seconds: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    late_threshold_minutes: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    late_threshold_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    class_start_time: Mapped[str] = mapped_column(String, nullable=False)
    class_end_time: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    attendance_mode: Mapped[str] = mapped_column(
        String, default="attendance", server_default="attendance", nullable=False
    )
    track_checkout: Mapped[bool] = mapped_column(Boolean, default=False)
    min_checkout_delay_minutes: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, default=15
    )
    scan_behavior: Mapped[str] = mapped_column(
        String, default="automatic", server_default="automatic", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )

    group: Mapped["AttendanceGroup"] = relationship(back_populates="rule_history")

    __table_args__ = (
        Index("ix_group_rule_group_id", "group_id"),
        Index(
            "ix_group_rule_group_effective_from",
            "group_id",
            "effective_from",
            unique=False,
        ),
    )


class AttendanceSettings(Base, SyncMixin):
    __tablename__ = "attendance_settings"
    session_policy_updated_at_utc: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
    )

    # The unique partial index below covers organization lookups. Do not also
    # create the mixin's redundant non-unique organization index.
    organization_id: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, index=False
    )
    attendance_timezone: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    late_threshold_minutes: Mapped[int] = mapped_column(Integer, default=15)
    enable_location_tracking: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence_threshold: Mapped[float] = mapped_column(
        Float, default=FACE_DETECTOR_CONFIG["score_threshold"]
    )
    attendance_cooldown_seconds: Mapped[int] = mapped_column(Integer, default=300)
    # Longer anti-duplicate window (e.g., 30 minutes) to prevent re-logging.
    relog_cooldown_seconds: Mapped[int] = mapped_column(Integer, default=1800)
    enable_liveness_detection: Mapped[bool] = mapped_column(Boolean, default=False)
    cloud_force_liveness: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    max_recognition_faces_per_frame: Mapped[int] = mapped_column(Integer, default=5)
    # Compliance: auto-purge records older than N days (0 = keep forever)
    data_retention_days: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        Index(
            "ux_attendance_settings_organization_id",
            "organization_id",
            unique=True,
            sqlite_where=text("organization_id IS NOT NULL"),
        ),
    )


class Face(Base, SyncMixin, DirectorySyncState):
    __tablename__ = "faces"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    person_id: Mapped[str] = mapped_column(String, nullable=False)
    embedding: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    hash: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )

    __table_args__ = (
        Index("ix_face_person_id", "person_id"),
        Index(
            "ux_face_person_global",
            "person_id",
            unique=True,
            sqlite_where=text("organization_id IS NULL"),
        ),
        Index(
            "ux_face_person_org",
            "person_id",
            "organization_id",
            unique=True,
            sqlite_where=text("organization_id IS NOT NULL"),
        ),
    )


class FaceAngleTemplate(Base):
    """Encrypted per-angle 512-d facial templates stored locally for pose-robust matching."""

    __tablename__ = "face_angle_templates"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    person_id: Mapped[str] = mapped_column(String, nullable=False)
    organization_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    angle: Mapped[str] = mapped_column(String, nullable=False)
    embedding: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    yaw: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    pitch: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    clarity_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )

    __table_args__ = (
        Index("ix_face_angle_person", "person_id"),
        Index(
            "ux_face_angle_global",
            "person_id",
            "angle",
            unique=True,
            sqlite_where=text("organization_id IS NULL"),
        ),
        Index(
            "ux_face_angle_org",
            "person_id",
            "organization_id",
            "angle",
            unique=True,
            sqlite_where=text("organization_id IS NOT NULL"),
        ),
    )


class AuditLog(Base):
    """Immutable audit trail for sensitive administrative actions."""

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), index=True
    )
    action: Mapped[str] = mapped_column(String, nullable=False, index=True)
    target_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    target_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    organization_id: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, index=True
    )

    __table_args__ = (
        Index("ix_audit_timestamp", "timestamp"),
        Index("ix_audit_action", "action"),
    )


class CctvCamera(Base):
    """Registered CCTV, webcam, RTSP, video, or simulated classroom cameras."""

    __tablename__ = "cctv_cameras"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    camera_code: Mapped[str] = mapped_column(String, nullable=False)
    source_type: Mapped[str] = mapped_column(String, nullable=False, default="webcam")
    source_uri: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    supports_ir: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    department: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    building: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    classroom: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    assigned_group_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("attendance_groups.id"), nullable=True
    )
    backup_camera_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="online")
    recording_status: Mapped[str] = mapped_column(
        String, nullable=False, default="idle"
    )
    quality_status: Mapped[str] = mapped_column(String, nullable=False, default="green")
    quality_score: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    fps: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reconnect_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_frame_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_connected_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    disconnected_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )
    organization_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("ix_cctv_cameras_code", "camera_code"),
        Index("ix_cctv_cameras_group", "assigned_group_id"),
        Index("ix_cctv_cameras_org", "organization_id"),
    )


class CctvCameraLog(Base):
    """Real-time error, disconnect, image quality, and recovery audit log for cameras."""

    __tablename__ = "cctv_camera_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    camera_id: Mapped[str] = mapped_column(
        String, ForeignKey("cctv_cameras.id"), nullable=False
    )
    error_category: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False, default="warning")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    recovery_status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending"
    )
    corrective_action: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    organization_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("ix_cctv_camera_logs_camera", "camera_id"),
        Index("ix_cctv_camera_logs_detected", "detected_at"),
        Index("ix_cctv_camera_logs_org", "organization_id"),
    )


class AcademicSchedule(Base):
    """Timetable entry binding department, semester, section, subject, faculty, classroom, and camera."""

    __tablename__ = "academic_schedules"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    group_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("attendance_groups.id"), nullable=True
    )
    department: Mapped[str] = mapped_column(String, nullable=False)
    semester: Mapped[str] = mapped_column(String, nullable=False)
    section: Mapped[str] = mapped_column(String, nullable=False)
    subject_code: Mapped[str] = mapped_column(String, nullable=False)
    subject_name: Mapped[str] = mapped_column(String, nullable=False)
    faculty_name: Mapped[str] = mapped_column(String, nullable=False)
    classroom: Mapped[str] = mapped_column(String, nullable=False)
    building: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    camera_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("cctv_cameras.id"), nullable=True
    )
    day_of_week: Mapped[str] = mapped_column(String, nullable=False, default="*")
    start_time: Mapped[str] = mapped_column(String, nullable=False)
    end_time: Mapped[str] = mapped_column(String, nullable=False)
    late_after_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    early_exit_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    min_presence_percent: Mapped[float] = mapped_column(
        Float, nullable=False, default=60.0
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )
    organization_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("ix_academic_schedules_group", "group_id"),
        Index("ix_academic_schedules_camera", "camera_id"),
        Index("ix_academic_schedules_section", "department", "semester", "section"),
        Index("ix_academic_schedules_org", "organization_id"),
    )


class StudentAcademicProfile(Base):
    """Academic metadata, registration number, and biometric consent preferences per member."""

    __tablename__ = "student_academic_profiles"

    member_id: Mapped[str] = mapped_column(
        String, ForeignKey("attendance_members.id"), primary_key=True
    )
    registration_number: Mapped[str] = mapped_column(String, nullable=False)
    department: Mapped[str] = mapped_column(String, nullable=False)
    semester: Mapped[str] = mapped_column(String, nullable=False)
    section: Mapped[str] = mapped_column(String, nullable=False)
    biometric_consent_granted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    consent_timestamp: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    non_biometric_opt_out: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    organization_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("ix_student_profiles_reg_no", "registration_number"),
        Index("ix_student_profiles_section", "department", "semester", "section"),
        Index("ix_student_profiles_org", "organization_id"),
    )


class CrossSectionException(Base):
    """Authorized cross-section attendance arrangement (combined, substitute, inter-section)."""

    __tablename__ = "cross_section_exceptions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    member_id: Mapped[str] = mapped_column(
        String, ForeignKey("attendance_members.id"), nullable=False
    )
    person_id: Mapped[str] = mapped_column(String, nullable=False)
    from_section: Mapped[str] = mapped_column(String, nullable=False)
    target_schedule_id: Mapped[str] = mapped_column(
        String, ForeignKey("academic_schedules.id"), nullable=False
    )
    target_section: Mapped[str] = mapped_column(String, nullable=False)
    exception_type: Mapped[str] = mapped_column(
        String, nullable=False, default="combined_lecture"
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    authorized_by: Mapped[str] = mapped_column(String, nullable=False)
    valid_date: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="approved")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )
    organization_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("ix_cross_section_member", "member_id"),
        Index("ix_cross_section_schedule", "target_schedule_id", "valid_date"),
        Index("ix_cross_section_org", "organization_id"),
    )


class UnknownStudentDetection(Base):
    """Unidentified face captures queued for authorized identity verification & registration."""

    __tablename__ = "unknown_student_detections"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tracking_id: Mapped[str] = mapped_column(String, nullable=False)
    camera_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    schedule_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    group_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    classroom: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
    frame_snapshot_enc: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary, nullable=True
    )
    embedding_enc: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    confidence_best_guess: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    resolved_member_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    resolved_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    organization_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("ix_unknown_detections_status", "status"),
        Index("ix_unknown_detections_detected", "detected_at"),
        Index("ix_unknown_detections_org", "organization_id"),
    )


class SmartAttendanceEvaluation(Base):
    """Evidence-based centralized verification result, entry/exit duration, and classification."""

    __tablename__ = "smart_attendance_evaluations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    schedule_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    group_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    camera_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    date: Mapped[str] = mapped_column(String, nullable=False)
    member_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    person_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    tracking_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    expected_section: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    detected_section: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    classification: Mapped[str] = mapped_column(
        String, nullable=False, default="pending_verification"
    )
    attendance_rule_status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending_verification"
    )
    recognition_confidence: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    image_quality_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0
    )
    face_visibility_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0
    )
    temporal_consistency_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    head_pose_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    duplicate_flagged: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    first_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    estimated_duration_minutes: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    observations_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verified_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )
    organization_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("ix_smart_eval_schedule_date", "schedule_id", "date"),
        Index("ix_smart_eval_group_date", "group_id", "date"),
        Index("ix_smart_eval_member_date", "member_id", "date"),
        Index("ix_smart_eval_classification", "classification"),
        Index("ix_smart_eval_org", "organization_id"),
    )


class SectionMismatchAlert(Base):
    """Unassigned section detection logged for faculty/admin review."""

    __tablename__ = "section_mismatch_alerts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    member_id: Mapped[str] = mapped_column(String, nullable=False)
    person_id: Mapped[str] = mapped_column(String, nullable=False)
    student_name: Mapped[str] = mapped_column(String, nullable=False)
    registration_number: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    actual_section: Mapped[str] = mapped_column(String, nullable=False)
    scheduled_section: Mapped[str] = mapped_column(String, nullable=False)
    schedule_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    camera_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    classroom: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="open")
    resolved_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    organization_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("ix_section_mismatch_status", "status"),
        Index("ix_section_mismatch_schedule", "schedule_id"),
        Index("ix_section_mismatch_org", "organization_id"),
    )


class VLaserCameraConfig(Base):
    """Virtual Laser (V-LASER) grid lines and zone boundary configuration per camera/classroom."""

    __tablename__ = "vlaser_camera_configs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    camera_id: Mapped[str] = mapped_column(
        String, ForeignKey("cctv_cameras.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    classroom: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    grid_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    grid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    grid_cols: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    grid_color: Mapped[str] = mapped_column(String, nullable=False, default="#00f3ff")
    grid_opacity: Mapped[float] = mapped_column(Float, nullable=False, default=0.25)
    lines_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    zones_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )
    organization_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("ix_vlaser_configs_camera", "camera_id"),
        Index("ix_vlaser_configs_classroom", "classroom"),
        Index("ix_vlaser_configs_org", "organization_id"),
    )


class ClassSessionRecording(Base):
    """Stored CCTV video recording clip for a specific class session."""

    __tablename__ = "class_session_recordings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    schedule_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("academic_schedules.id", ondelete="SET NULL"), nullable=True
    )
    course_code: Mapped[str] = mapped_column(String, nullable=False)
    course_name: Mapped[str] = mapped_column(String, nullable=False)
    section: Mapped[str] = mapped_column(String, nullable=False)
    session_date: Mapped[str] = mapped_column(String, nullable=False)  # YYYY-MM-DD
    start_time: Mapped[str] = mapped_column(String, nullable=False)  # HH:MM
    end_time: Mapped[str] = mapped_column(String, nullable=False)  # HH:MM
    classroom: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    camera_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("cctv_cameras.id", ondelete="SET NULL"), nullable=True
    )
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    format: Mapped[str] = mapped_column(String, nullable=False, default="mp4")
    status: Mapped[str] = mapped_column(String, nullable=False, default="ready")  # ready, processing, deleted
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
    created_by: Mapped[str] = mapped_column(String, nullable=False, default="system")
    organization_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("ix_recordings_course_section", "course_code", "section", "session_date"),
        Index("ix_recordings_schedule", "schedule_id"),
        Index("ix_recordings_status", "status"),
        Index("ix_recordings_org", "organization_id"),
    )


class AttendanceCorrectionAudit(Base):
    """Audit log tracking who changed student attendance, when, and the reason."""

    __tablename__ = "attendance_correction_audits"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    recording_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("class_session_recordings.id", ondelete="SET NULL"), nullable=True
    )
    schedule_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("academic_schedules.id", ondelete="SET NULL"), nullable=True
    )
    member_id: Mapped[str] = mapped_column(
        String, ForeignKey("attendance_members.id", ondelete="CASCADE"), nullable=False
    )
    student_name: Mapped[str] = mapped_column(String, nullable=False)
    session_date: Mapped[str] = mapped_column(String, nullable=False)
    previous_status: Mapped[str] = mapped_column(String, nullable=False)
    new_status: Mapped[str] = mapped_column(String, nullable=False)
    correction_reason: Mapped[str] = mapped_column(Text, nullable=False)
    corrected_by: Mapped[str] = mapped_column(String, nullable=False)  # Faculty name/ID
    corrected_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
    organization_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("ix_attendance_audit_member", "member_id"),
        Index("ix_attendance_audit_recording", "recording_id"),
        Index("ix_attendance_audit_date", "session_date"),
        Index("ix_attendance_audit_org", "organization_id"),
    )


class VideoAccessAudit(Base):
    """Audit log tracking who played, seeked, or viewed stored class video clips."""

    __tablename__ = "video_access_audits"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    recording_id: Mapped[str] = mapped_column(
        String, ForeignKey("class_session_recordings.id", ondelete="CASCADE"), nullable=False
    )
    accessed_by: Mapped[str] = mapped_column(String, nullable=False)
    access_type: Mapped[str] = mapped_column(String, nullable=False, default="stream_play")
    ip_address: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    accessed_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
    organization_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("ix_video_audit_recording", "recording_id"),
        Index("ix_video_audit_user", "accessed_by"),
        Index("ix_video_audit_org", "organization_id"),
    )


# Track all ORM write paths, including enrollment and backup restore. Remote imports
# suppress this listener within their transaction and set the acknowledged revision.
_SYNC_FIELDS = {
    AttendanceGroup: (
        "name",
        "is_active",
        "is_deleted",
        "late_threshold_minutes",
        "late_threshold_enabled",
        "class_start_time",
        "class_end_time",
        "attendance_mode",
        "track_checkout",
        "min_checkout_delay_minutes",
        "scan_behavior",
    ),
    AttendanceMember: (
        "person_id",
        "name",
        "group_id",
        "role",
        "email",
        "is_active",
        "is_deleted",
    ),
    Face: ("person_id", "embedding", "is_deleted"),
}


@event.listens_for(Session, "before_flush")
def track_directory_edits(session, _flush_context, _instances):
    if session.info.get("sync_import"):
        return
    for obj in session.dirty:
        fields = _SYNC_FIELDS.get(type(obj))
        if fields and any(inspect(obj).attrs[f].history.has_changes() for f in fields):
            obj.sync_dirty = True
            obj.version = (obj.version or 0) + 1
