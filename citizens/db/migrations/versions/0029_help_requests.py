# SPDX-License-Identifier: AGPL-3.0-or-later
"""help_requests — a table raising its hand.

A table with a problem used to have one way to reach the organizer: someone
walking across the room. One tap on the phone now stores a request — what
kind, which table, which recorder — and the Live tab shows it beside the
table's number until the organizer acknowledges it. One open request per
table at a time: tapping again changes the kind rather than stacking rows.
"""
import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "help_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "assembly_id", sa.String(36), sa.ForeignKey("assemblies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "round_id", sa.String(36), sa.ForeignKey("rounds.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("table_number", sa.Integer(), nullable=False),
        sa.Column("slot", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.String(64), nullable=True),
    )
    op.create_index("ix_help_requests_assembly_id", "help_requests", ["assembly_id"])


def downgrade():
    op.drop_index("ix_help_requests_assembly_id", table_name="help_requests")
    op.drop_table("help_requests")
