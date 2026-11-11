"""Lock down persisted SAMIHS output in the public schema.

Revision ID: 20261111_0008
Revises: 20261111_0007
"""

from alembic import op

revision = "20261111_0008"
down_revision = "20261111_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE public.study_localizations ENABLE ROW LEVEL SECURITY")
        op.execute(
            "REVOKE ALL ON TABLE public.study_localizations FROM anon, authenticated, public"
        )
    op.create_index(
        "ix_study_localizations_model_version_id",
        "study_localizations",
        ["model_version_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_study_localizations_model_version_id", table_name="study_localizations"
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE public.study_localizations DISABLE ROW LEVEL SECURITY")
        op.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES, TRIGGER "
            "ON TABLE public.study_localizations TO anon, authenticated"
        )
