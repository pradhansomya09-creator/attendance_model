"""add encrypted multi-angle face template storage

Revision ID: u6v7w8x9y0z1
Revises: t5u6v7w8x9y0
Create Date: 2026-11-12 19:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "u6v7w8x9y0z1"
down_revision: Union[str, Sequence[str], None] = "t5u6v7w8x9y0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "face_angle_templates",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("person_id", sa.String(), nullable=False),
        sa.Column("organization_id", sa.String(), nullable=True),
        sa.Column("angle", sa.String(), nullable=False),
        sa.Column("embedding", sa.LargeBinary(), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("yaw", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("pitch", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("clarity_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_face_angle_person", "face_angle_templates", ["person_id"])
    op.create_index(
        "ux_face_angle_global",
        "face_angle_templates",
        ["person_id", "angle"],
        unique=True,
        sqlite_where=sa.text("organization_id IS NULL"),
    )
    op.create_index(
        "ux_face_angle_org",
        "face_angle_templates",
        ["person_id", "organization_id", "angle"],
        unique=True,
        sqlite_where=sa.text("organization_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ux_face_angle_org", table_name="face_angle_templates")
    op.drop_index("ux_face_angle_global", table_name="face_angle_templates")
    op.drop_index("ix_face_angle_person", table_name="face_angle_templates")
    op.drop_table("face_angle_templates")

