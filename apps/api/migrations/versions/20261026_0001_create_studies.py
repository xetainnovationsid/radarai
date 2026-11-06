"""Create studies and study slices tables."""

import sqlalchemy as sa
from alembic import op

revision = "20261026_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "studies",
        sa.Column("study_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("modality", sa.String(length=8), server_default="CT", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="uploaded", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("modality = 'CT'", name="ck_studies_modality_ct"),
        sa.CheckConstraint(
            "status IN ('uploaded', 'processing', 'ready', 'failed')", name="ck_studies_status"
        ),
        sa.PrimaryKeyConstraint("study_id"),
    )
    op.create_table(
        "study_slices",
        sa.Column("slice_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("study_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("index", sa.Integer(), nullable=False),
        sa.Column("image_asset_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("z_position_mm", sa.Float(), nullable=True),
        sa.CheckConstraint('"index" >= 0', name="ck_study_slices_index_nonnegative"),
        sa.ForeignKeyConstraint(["study_id"], ["studies.study_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("slice_id"),
        sa.UniqueConstraint("study_id", "index", name="uq_study_slices_study_index"),
    )
    op.create_index("ix_study_slices_study_id", "study_slices", ["study_id"])


def downgrade() -> None:
    op.drop_index("ix_study_slices_study_id", table_name="study_slices")
    op.drop_table("study_slices")
    op.drop_table("studies")
