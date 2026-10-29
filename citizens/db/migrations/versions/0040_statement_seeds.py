# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Polis statement seeds (0.9): short, neutral statements written from an
assembly's approved findings, reviewed by the organizer and exported for a
Polis conversation. Statement text only — no evidence, no names.

`finding_id` is SET NULL when a re-run of the analysis replaces the finding
the seed came from; the seed survives as a manual one, marked stale.
"""
import sqlalchemy as sa
from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "statement_seeds",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "assembly_id", sa.String(36),
            sa.ForeignKey("assemblies.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "finding_id", sa.String(36),
            sa.ForeignKey("findings.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("language", sa.String(10), nullable=False, server_default="en"),
        sa.Column("status", sa.String(16), nullable=False, server_default="DRAFT"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("origin", sa.String(8), nullable=False, server_default="ai"),
        sa.Column("stale", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("reviewed_by", sa.String(64), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("polis_conversation_id", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_statement_seeds_assembly_id", "statement_seeds", ["assembly_id"])
    op.create_index("ix_statement_seeds_finding_id", "statement_seeds", ["finding_id"])


def downgrade():
    op.drop_index("ix_statement_seeds_finding_id", table_name="statement_seeds")
    op.drop_index("ix_statement_seeds_assembly_id", table_name="statement_seeds")
    op.drop_table("statement_seeds")
