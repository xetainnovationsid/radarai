"""Allow the private API database role to persist SAMIHS results.

Revision ID: 20261111_0009
Revises: 20261111_0008
"""

from alembic import op

revision = "20261111_0009"
down_revision = "20261111_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "GRANT SELECT, INSERT ON TABLE public.study_localizations TO radar_backend"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "REVOKE SELECT, INSERT ON TABLE public.study_localizations FROM radar_backend"
        )
