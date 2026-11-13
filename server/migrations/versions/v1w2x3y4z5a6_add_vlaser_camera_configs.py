"""add vlaser camera configs for virtual grid, lines, and zones

Revision ID: v1w2x3y4z5a6
Revises: u6v7w8x9y0z1
Create Date: 2026-11-13 01:27:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "v1w2x3y4z5a6"
down_revision: Union[str, Sequence[str], None] = "u6v7w8x9y0z1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vlaser_camera_configs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column(
            "camera_id",
            sa.String(),
            sa.ForeignKey("cctv_cameras.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("classroom", sa.String(), nullable=True),
        sa.Column("grid_enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("grid_rows", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("grid_cols", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("grid_color", sa.String(), nullable=False, server_default="#00f3ff"),
        sa.Column("grid_opacity", sa.Float(), nullable=False, server_default="0.25"),
        sa.Column("lines_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("zones_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_vlaser_configs_camera", "vlaser_camera_configs", ["camera_id"])
    op.create_index("ix_vlaser_configs_classroom", "vlaser_camera_configs", ["classroom"])
    op.create_index("ix_vlaser_configs_org", "vlaser_camera_configs", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_vlaser_configs_org", table_name="vlaser_camera_configs")
    op.drop_index("ix_vlaser_configs_classroom", table_name="vlaser_camera_configs")
    op.drop_index("ix_vlaser_configs_camera", table_name="vlaser_camera_configs")
    op.drop_table("vlaser_camera_configs")

