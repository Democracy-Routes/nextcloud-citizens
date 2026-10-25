# SPDX-License-Identifier: AGPL-3.0-or-later
"""summary_validations — participants say whether their table's summary
reflects the discussion (0.7).

After the organizer publishes the report, a person who registered on their
own phone sees the summary of the table they sat at and can say "Looks right"
or "Something is missing" (with a note). One answer per person and session;
the organizer sees the counts and the notes beside each table, the report
counts them in its coverage. Never a vote, never an edit: a flag for a human
to look at.
"""
import sqlalchemy as sa
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "summary_validations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "assembly_id", sa.String(36), sa.ForeignKey("assemblies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "round_id", sa.String(36), sa.ForeignKey("rounds.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "participant_id", sa.String(36),
            sa.ForeignKey("participants.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("table_number", sa.Integer(), nullable=True),
        sa.Column("verdict", sa.String(16), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("round_id", "participant_id", name="uq_summary_validation_once"),
    )
    op.create_index("ix_summary_validations_assembly_id", "summary_validations", ["assembly_id"])


def downgrade():
    op.drop_index("ix_summary_validations_assembly_id", table_name="summary_validations")
    op.drop_table("summary_validations")
