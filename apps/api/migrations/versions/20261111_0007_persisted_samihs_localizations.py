"""Persist SAMIHS output produced by the laptop worker.

Revision ID: 20261111_0007
Revises: 20261111_0006
"""

import sqlalchemy as sa
from alembic import op

revision = "20261111_0007"
down_revision = "20261111_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "study_localizations",
        sa.Column("localization_id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("model_version_id", sa.Uuid(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("slices", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["study_id"], ["studies.study_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["model_version_id"], ["model_versions.model_version_id"]),
        sa.PrimaryKeyConstraint("localization_id"),
        sa.CheckConstraint(
            "threshold > 0 AND threshold < 1", name="ck_study_localizations_threshold"
        ),
    )
    op.create_index(
        "ix_study_localizations_study_created",
        "study_localizations",
        ["study_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_study_localizations_study_created", table_name="study_localizations")
    op.drop_table("study_localizations")
