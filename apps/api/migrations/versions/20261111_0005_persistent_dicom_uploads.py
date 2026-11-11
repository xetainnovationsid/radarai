"""Persist DICOM slices in Supabase and support resumable uploads.

Revision ID: 20261111_0005
Revises: 20261105_0004
"""

import sqlalchemy as sa
from alembic import op

revision = "20261111_0005"
down_revision = "20261105_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("studies", sa.Column("upload_expected_slices", sa.Integer(), nullable=True))
    op.add_column(
        "study_slices",
        sa.Column("dicom_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column("image_assets", sa.Column("dicom_data", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    op.drop_column("image_assets", "dicom_data")
    op.drop_column("study_slices", "dicom_metadata")
    op.drop_column("studies", "upload_expected_slices")
