"""Add study ownership, persisted inference jobs/scores, and report drafts.

Revision ID: 20261105_0004
Revises: 20261026_0003
"""

import sqlalchemy as sa
from alembic import op

revision = "20261105_0004"
down_revision = "20261026_0003"
branch_labels = None
depends_on = None


def uuid_type():
    return sa.Uuid(as_uuid=True)


def upgrade() -> None:
    op.add_column(
        "studies",
        sa.Column(
            "owner_id", sa.String(length=64), nullable=False, server_default="local-reviewer"
        ),
    )
    op.add_column(
        "model_versions", sa.Column("preprocessing_version", sa.String(80), nullable=True)
    )
    op.add_column("model_versions", sa.Column("artifact_sha256", sa.String(64), nullable=True))
    op.add_column("model_versions", sa.Column("device", sa.String(16), nullable=True))
    op.add_column(
        "findings",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "finding_review_events",
        sa.Column("action", sa.String(16), nullable=False, server_default="review"),
    )
    op.add_column(
        "finding_review_events",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "finding_review_events", sa.Column("previous_snapshot", sa.JSON(), nullable=True)
    )
    op.add_column(
        "finding_review_events", sa.Column("current_snapshot", sa.JSON(), nullable=True)
    )
    op.create_table(
        "inference_jobs",
        sa.Column("job_id", uuid_type(), primary_key=True, nullable=False),
        sa.Column(
            "study_id",
            uuid_type(),
            sa.ForeignKey("studies.study_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("requested_by", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_code", sa.String(48), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'failed')",
            name="ck_inference_jobs_status",
        ),
    )
    op.create_index("ix_inference_jobs_study_created", "inference_jobs", ["study_id", "created_at"])
    op.create_table(
        "inference_scores",
        sa.Column("score_id", uuid_type(), primary_key=True, nullable=False),
        sa.Column(
            "analysis_id",
            uuid_type(),
            sa.ForeignKey("study_analyses.analysis_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "study_id",
            uuid_type(),
            sa.ForeignKey("studies.study_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "slice_id",
            uuid_type(),
            sa.ForeignKey("study_slices.slice_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "model_version_id",
            uuid_type(),
            sa.ForeignKey("model_versions.model_version_id"),
            nullable=False,
        ),
        sa.Column("subtype", sa.String(80), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.CheckConstraint("score >= 0 AND score <= 1", name="ck_inference_scores_range"),
        sa.UniqueConstraint(
            "analysis_id", "slice_id", "subtype", name="uq_inference_score_analysis_slice"
        ),
    )
    op.create_table(
        "report_drafts",
        sa.Column("report_id", uuid_type(), primary_key=True, nullable=False),
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
            nullable=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source_finding_ids", sa.JSON(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'approved', 'rejected')", name="ck_report_drafts_status"
        ),
        sa.UniqueConstraint("study_id", "version", name="uq_report_draft_version"),
    )


def downgrade() -> None:
    op.drop_table("report_drafts")
    op.drop_table("inference_scores")
    op.drop_index("ix_inference_jobs_study_created", table_name="inference_jobs")
    op.drop_table("inference_jobs")
    op.drop_column("finding_review_events", "current_snapshot")
    op.drop_column("finding_review_events", "previous_snapshot")
    op.drop_column("finding_review_events", "version")
    op.drop_column("finding_review_events", "action")
    op.drop_column("findings", "revision")
    op.drop_column("model_versions", "device")
    op.drop_column("model_versions", "artifact_sha256")
    op.drop_column("model_versions", "preprocessing_version")
    op.drop_column("studies", "owner_id")
