"""Add CCTV camera monitoring, academic schedules, unknown detections, and smart attendance evaluation tables."""

from alembic import op
import sqlalchemy as sa

revision = "t5u6v7w8x9y0"
down_revision = "s4t5u6v7w8x9"
branch_labels = None
depends_on = None


def upgrade():
    now = sa.text("CURRENT_TIMESTAMP")

    op.create_table(
        "cctv_cameras",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("camera_code", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_uri", sa.String(), nullable=True),
        sa.Column("supports_ir", sa.Boolean(), nullable=False),
        sa.Column("department", sa.String(), nullable=True),
        sa.Column("building", sa.String(), nullable=True),
        sa.Column("classroom", sa.String(), nullable=True),
        sa.Column(
            "assigned_group_id",
            sa.String(),
            sa.ForeignKey("attendance_groups.id"),
            nullable=True,
        ),
        sa.Column("backup_camera_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("recording_status", sa.String(), nullable=False),
        sa.Column("quality_status", sa.String(), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=False),
        sa.Column("fps", sa.Float(), nullable=False),
        sa.Column("reconnect_attempts", sa.Integer(), nullable=False),
        sa.Column("last_frame_at", sa.DateTime(), nullable=True),
        sa.Column("last_connected_at", sa.DateTime(), nullable=True),
        sa.Column("disconnected_at", sa.DateTime(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=now, nullable=False),
        sa.Column("organization_id", sa.String(), nullable=True),
    )
    op.create_index("ix_cctv_cameras_code", "cctv_cameras", ["camera_code"])
    op.create_index("ix_cctv_cameras_group", "cctv_cameras", ["assigned_group_id"])
    op.create_index("ix_cctv_cameras_org", "cctv_cameras", ["organization_id"])

    op.create_table(
        "cctv_camera_logs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "camera_id", sa.String(), sa.ForeignKey("cctv_cameras.id"), nullable=False
        ),
        sa.Column("error_category", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("detected_at", sa.DateTime(), server_default=now, nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("recovery_status", sa.String(), nullable=False),
        sa.Column("corrective_action", sa.Text(), nullable=True),
        sa.Column("organization_id", sa.String(), nullable=True),
    )
    op.create_index("ix_cctv_camera_logs_camera", "cctv_camera_logs", ["camera_id"])
    op.create_index(
        "ix_cctv_camera_logs_detected", "cctv_camera_logs", ["detected_at"]
    )
    op.create_index("ix_cctv_camera_logs_org", "cctv_camera_logs", ["organization_id"])

    op.create_table(
        "academic_schedules",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "group_id",
            sa.String(),
            sa.ForeignKey("attendance_groups.id"),
            nullable=True,
        ),
        sa.Column("department", sa.String(), nullable=False),
        sa.Column("semester", sa.String(), nullable=False),
        sa.Column("section", sa.String(), nullable=False),
        sa.Column("subject_code", sa.String(), nullable=False),
        sa.Column("subject_name", sa.String(), nullable=False),
        sa.Column("faculty_name", sa.String(), nullable=False),
        sa.Column("classroom", sa.String(), nullable=False),
        sa.Column("building", sa.String(), nullable=True),
        sa.Column(
            "camera_id", sa.String(), sa.ForeignKey("cctv_cameras.id"), nullable=True
        ),
        sa.Column("day_of_week", sa.String(), nullable=False),
        sa.Column("start_time", sa.String(), nullable=False),
        sa.Column("end_time", sa.String(), nullable=False),
        sa.Column("late_after_minutes", sa.Integer(), nullable=False),
        sa.Column("early_exit_minutes", sa.Integer(), nullable=False),
        sa.Column("min_presence_percent", sa.Float(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=now, nullable=False),
        sa.Column("organization_id", sa.String(), nullable=True),
    )
    op.create_index("ix_academic_schedules_group", "academic_schedules", ["group_id"])
    op.create_index("ix_academic_schedules_camera", "academic_schedules", ["camera_id"])
    op.create_index(
        "ix_academic_schedules_section",
        "academic_schedules",
        ["department", "semester", "section"],
    )
    op.create_index(
        "ix_academic_schedules_org", "academic_schedules", ["organization_id"]
    )

    op.create_table(
        "student_academic_profiles",
        sa.Column(
            "member_id",
            sa.String(),
            sa.ForeignKey("attendance_members.id"),
            primary_key=True,
        ),
        sa.Column("registration_number", sa.String(), nullable=False),
        sa.Column("department", sa.String(), nullable=False),
        sa.Column("semester", sa.String(), nullable=False),
        sa.Column("section", sa.String(), nullable=False),
        sa.Column("biometric_consent_granted", sa.Boolean(), nullable=False),
        sa.Column("consent_timestamp", sa.DateTime(), nullable=True),
        sa.Column("non_biometric_opt_out", sa.Boolean(), nullable=False),
        sa.Column("organization_id", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_student_profiles_reg_no",
        "student_academic_profiles",
        ["registration_number"],
    )
    op.create_index(
        "ix_student_profiles_section",
        "student_academic_profiles",
        ["department", "semester", "section"],
    )
    op.create_index(
        "ix_student_profiles_org", "student_academic_profiles", ["organization_id"]
    )

    op.create_table(
        "cross_section_exceptions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "member_id",
            sa.String(),
            sa.ForeignKey("attendance_members.id"),
            nullable=False,
        ),
        sa.Column("person_id", sa.String(), nullable=False),
        sa.Column("from_section", sa.String(), nullable=False),
        sa.Column(
            "target_schedule_id",
            sa.String(),
            sa.ForeignKey("academic_schedules.id"),
            nullable=False,
        ),
        sa.Column("target_section", sa.String(), nullable=False),
        sa.Column("exception_type", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("authorized_by", sa.String(), nullable=False),
        sa.Column("valid_date", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=now, nullable=False),
        sa.Column("organization_id", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_cross_section_member", "cross_section_exceptions", ["member_id"]
    )
    op.create_index(
        "ix_cross_section_schedule",
        "cross_section_exceptions",
        ["target_schedule_id", "valid_date"],
    )
    op.create_index(
        "ix_cross_section_org", "cross_section_exceptions", ["organization_id"]
    )

    op.create_table(
        "unknown_student_detections",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tracking_id", sa.String(), nullable=False),
        sa.Column("camera_id", sa.String(), nullable=True),
        sa.Column("schedule_id", sa.String(), nullable=True),
        sa.Column("group_id", sa.String(), nullable=True),
        sa.Column("classroom", sa.String(), nullable=True),
        sa.Column("detected_at", sa.DateTime(), server_default=now, nullable=False),
        sa.Column("frame_snapshot_enc", sa.LargeBinary(), nullable=True),
        sa.Column("embedding_enc", sa.LargeBinary(), nullable=True),
        sa.Column("confidence_best_guess", sa.Float(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("resolved_member_id", sa.String(), nullable=True),
        sa.Column("resolved_by", sa.String(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("organization_id", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_unknown_detections_status", "unknown_student_detections", ["status"]
    )
    op.create_index(
        "ix_unknown_detections_detected",
        "unknown_student_detections",
        ["detected_at"],
    )
    op.create_index(
        "ix_unknown_detections_org",
        "unknown_student_detections",
        ["organization_id"],
    )

    op.create_table(
        "smart_attendance_evaluations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("schedule_id", sa.String(), nullable=True),
        sa.Column("group_id", sa.String(), nullable=True),
        sa.Column("camera_id", sa.String(), nullable=True),
        sa.Column("date", sa.String(), nullable=False),
        sa.Column("member_id", sa.String(), nullable=True),
        sa.Column("person_id", sa.String(), nullable=True),
        sa.Column("tracking_id", sa.String(), nullable=True),
        sa.Column("expected_section", sa.String(), nullable=True),
        sa.Column("detected_section", sa.String(), nullable=True),
        sa.Column("classification", sa.String(), nullable=False),
        sa.Column("attendance_rule_status", sa.String(), nullable=False),
        sa.Column("recognition_confidence", sa.Float(), nullable=False),
        sa.Column("image_quality_score", sa.Float(), nullable=False),
        sa.Column("face_visibility_score", sa.Float(), nullable=False),
        sa.Column("temporal_consistency_score", sa.Float(), nullable=False),
        sa.Column("head_pose_ok", sa.Boolean(), nullable=False),
        sa.Column("duplicate_flagged", sa.Boolean(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("estimated_duration_minutes", sa.Float(), nullable=False),
        sa.Column("observations_count", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("verified_by", sa.String(), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=now, nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=now, nullable=False),
        sa.Column("organization_id", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_smart_eval_schedule_date",
        "smart_attendance_evaluations",
        ["schedule_id", "date"],
    )
    op.create_index(
        "ix_smart_eval_group_date",
        "smart_attendance_evaluations",
        ["group_id", "date"],
    )
    op.create_index(
        "ix_smart_eval_member_date",
        "smart_attendance_evaluations",
        ["member_id", "date"],
    )
    op.create_index(
        "ix_smart_eval_classification",
        "smart_attendance_evaluations",
        ["classification"],
    )
    op.create_index(
        "ix_smart_eval_org", "smart_attendance_evaluations", ["organization_id"]
    )

    op.create_table(
        "section_mismatch_alerts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("member_id", sa.String(), nullable=False),
        sa.Column("person_id", sa.String(), nullable=False),
        sa.Column("student_name", sa.String(), nullable=False),
        sa.Column("registration_number", sa.String(), nullable=True),
        sa.Column("actual_section", sa.String(), nullable=False),
        sa.Column("scheduled_section", sa.String(), nullable=False),
        sa.Column("schedule_id", sa.String(), nullable=True),
        sa.Column("camera_id", sa.String(), nullable=True),
        sa.Column("classroom", sa.String(), nullable=True),
        sa.Column("detected_at", sa.DateTime(), server_default=now, nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("resolved_by", sa.String(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("organization_id", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_section_mismatch_status", "section_mismatch_alerts", ["status"]
    )
    op.create_index(
        "ix_section_mismatch_schedule", "section_mismatch_alerts", ["schedule_id"]
    )
    op.create_index(
        "ix_section_mismatch_org", "section_mismatch_alerts", ["organization_id"]
    )


def downgrade():
    for table_name in (
        "section_mismatch_alerts",
        "smart_attendance_evaluations",
        "unknown_student_detections",
        "cross_section_exceptions",
        "student_academic_profiles",
        "academic_schedules",
        "cctv_camera_logs",
        "cctv_cameras",
    ):
        op.drop_table(table_name)

