"""Persist private image asset metadata and link study slices to assets."""

import sqlalchemy as sa
from alembic import op

revision = "20261026_0002"
down_revision = "20261026_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "image_assets",
        sa.Column("image_asset_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("storage_key", sa.String(length=128), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("size_bytes > 0", name="ck_image_assets_size_positive"),
        sa.PrimaryKeyConstraint("image_asset_id"),
        sa.UniqueConstraint("storage_key"),
    )
    with op.batch_alter_table("study_slices") as batch_op:
        batch_op.create_foreign_key(
            "fk_study_slices_image_asset_id",
            "image_assets",
            ["image_asset_id"],
            ["image_asset_id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    with op.batch_alter_table("study_slices") as batch_op:
        batch_op.drop_constraint("fk_study_slices_image_asset_id", type_="foreignkey")
    op.drop_table("image_assets")
