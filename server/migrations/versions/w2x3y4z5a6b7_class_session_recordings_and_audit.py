"""add class session recordings, attendance correction audits, and video access audits

Revision ID: w2x3y4z5a6b7
Revises: v1w2x3y4z5a6
Create Date: 2026-11-13 09:40:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "w2x3y4z5a6b7"
down_revision: Union[str, Sequence[str], None] = "v1w2x3y4z5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Class Session Recordings Table
    op.create_table(
        "class_session_recordings",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column(
            "schedule_id",
            sa.String(),
            sa.ForeignKey("academic_schedules.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("course_code", sa.String(), nullable=False),
        sa.Column("course_name", sa.String(), nullable=False),
        sa.Column("section", sa.String(), nullable=False),
        sa.Column("session_date", sa.String(), nullable=False),
        sa.Column("start_time", sa.String(), nullable=False),
        sa.Column("end_time", sa.String(), nullable=False),
        sa.Column("classroom", sa.String(), nullable=True),
        sa.Column(
            "camera_id",
            sa.String(),
            sa.ForeignKey("cctv_cameras.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_seconds", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("format", sa.String(), nullable=False, server_default="mp4"),
        sa.Column("status", sa.String(), nullable=False, server_default="ready"),
        sa.Column("retention_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(), nullable=False, server_default="system"),
        sa.Column("organization_id", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_recordings_course_section",
        "class_session_recordings",
        ["course_code", "section", "session_date"],
        unique=False,
    )
    op.create_index(
        "ix_recordings_schedule",
        "class_session_recordings",
        ["schedule_id"],
        unique=False,
    )
    op.create_index(
        "ix_recordings_status",
        "class_session_recordings",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_recordings_org",
        "class_session_recordings",
        ["organization_id"],
        unique=False,
    )

    # 2. Attendance Correction Audits Table
    op.create_table(
        "attendance_correction_audits",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column(
            "recording_id",
            sa.String(),
            sa.ForeignKey("class_session_recordings.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "schedule_id",
            sa.String(),
            sa.ForeignKey("academic_schedules.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "member_id",
            sa.String(),
            sa.ForeignKey("attendance_members.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("student_name", sa.String(), nullable=False),
        sa.Column("session_date", sa.String(), nullable=False),
        sa.Column("previous_status", sa.String(), nullable=False),
        sa.Column("new_status", sa.String(), nullable=False),
        sa.Column("correction_reason", sa.Text(), nullable=False),
        sa.Column("corrected_by", sa.String(), nullable=False),
        sa.Column(
            "corrected_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_attendance_audit_member",
        "attendance_correction_audits",
        ["member_id"],
        unique=False,
    )
    op.create_index(
        "ix_attendance_audit_recording",
        "attendance_correction_audits",
        ["recording_id"],
        unique=False,
    )
    op.create_index(
        "ix_attendance_audit_date",
        "attendance_correction_audits",
        ["session_date"],
        unique=False,
    )
    op.create_index(
        "ix_attendance_audit_org",
        "attendance_correction_audits",
        ["organization_id"],
        unique=False,
    )

    # 3. Video Access Audits Table
    op.create_table(
        "video_access_audits",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column(
            "recording_id",
            sa.String(),
            sa.ForeignKey("class_session_recordings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("accessed_by", sa.String(), nullable=False),
        sa.Column("access_type", sa.String(), nullable=False, server_default="stream_play"),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.Column(
            "accessed_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_video_audit_recording",
        "video_access_audits",
        ["recording_id"],
        unique=False,
    )
    op.create_index(
        "ix_video_audit_user",
        "video_access_audits",
        ["accessed_by"],
        unique=False,
    )
    op.create_index(
        "ix_video_audit_org",
        "video_access_audits",
        ["organization_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("video_access_audits")
    op.drop_table("attendance_correction_audits")
    op.drop_table("class_session_recordings")

