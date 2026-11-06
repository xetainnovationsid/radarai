"""Persist model outputs and review audit events.

Revision ID: 20261026_0003
Revises: 20261026_0002
"""

import sqlalchemy as sa
from alembic import op

revision = "20261026_0003"
down_revision = "20261026_0002"
branch_labels = None
depends_on = None


def uuid_type():
    return sa.Uuid(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "model_versions",
        sa.Column("model_version_id", uuid_type(), primary_key=True, nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model_id", sa.String(length=160), nullable=False),
        sa.Column("prompt_version", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "study_analyses",
        sa.Column("analysis_id", uuid_type(), primary_key=True, nullable=False),
        sa.Column(
            "study_id",
            uuid_type(),
            sa.ForeignKey("studies.study_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "model_version_id",
            uuid_type(),
            sa.ForeignKey("model_versions.model_version_id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_study_analyses_study_id", "study_analyses", ["study_id"])
    op.create_table(
        "findings",
        sa.Column("finding_id", uuid_type(), primary_key=True, nullable=False),
        sa.Column(
            "study_id",
            uuid_type(),
            sa.ForeignKey("studies.study_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("review_status", sa.String(length=16), nullable=False),
        sa.Column(
            "model_version_id",
            uuid_type(),
            sa.ForeignKey("model_versions.model_version_id"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "category = 'suspected_intracranial_hemorrhage'", name="ck_findings_category"
        ),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_findings_confidence"),
        sa.CheckConstraint(
            "review_status IN ('pending', 'accepted', 'rejected', 'uncertain')",
            name="ck_findings_review_status",
        ),
    )
    op.create_index("ix_findings_study_id", "findings", ["study_id"])
    op.create_table(
        "finding_evidence",
        sa.Column("evidence_id", uuid_type(), primary_key=True, nullable=False),
        sa.Column(
            "finding_id",
            uuid_type(),
            sa.ForeignKey("findings.finding_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "slice_id",
            uuid_type(),
            sa.ForeignKey("study_slices.slice_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.UniqueConstraint("finding_id", "slice_id", name="uq_finding_evidence"),
    )
    op.create_index("ix_finding_evidence_finding_id", "finding_evidence", ["finding_id"])
    op.create_table(
        "finding_review_events",
        sa.Column("review_event_id", uuid_type(), primary_key=True, nullable=False),
        sa.Column(
            "finding_id",
            uuid_type(),
            sa.ForeignKey("findings.finding_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("previous_review_status", sa.String(length=16), nullable=True),
        sa.Column("review_status", sa.String(length=16), nullable=False),
        sa.Column("reviewer", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "review_status IN ('accepted', 'rejected', 'uncertain')", name="ck_review_events_status"
        ),
    )
    op.create_index("ix_finding_review_events_finding_id", "finding_review_events", ["finding_id"])


def downgrade() -> None:
    op.drop_index("ix_finding_review_events_finding_id", table_name="finding_review_events")
    op.drop_table("finding_review_events")
    op.drop_index("ix_finding_evidence_finding_id", table_name="finding_evidence")
    op.drop_table("finding_evidence")
    op.drop_index("ix_findings_study_id", table_name="findings")
    op.drop_table("findings")
    op.drop_index("ix_study_analyses_study_id", table_name="study_analyses")
    op.drop_table("study_analyses")
    op.drop_table("model_versions")
