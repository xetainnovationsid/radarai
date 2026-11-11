"""Add renewable, fenced leases for laptop inference workers.

Revision ID: 20261111_0006
Revises: 20261111_0005
"""

import sqlalchemy as sa
from alembic import op

revision = "20261111_0006"
down_revision = "20261111_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("inference_jobs", sa.Column("lease_token", sa.Uuid(), nullable=True))
    op.add_column(
        "inference_jobs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "inference_jobs",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_column("inference_jobs", "attempt_count")
    op.drop_column("inference_jobs", "lease_expires_at")
    op.drop_column("inference_jobs", "lease_token")
