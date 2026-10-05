# SPDX-License-Identifier: AGPL-3.0-or-later
"""assemblies.synthesis_json — how the discussion developed across sessions.

A report listed each session's findings one after the other. An assembly
with several sessions is a journey — problems, options, concerns,
convergence, proposals — and the organizer asked for that chapter. The
synthesis is produced by the analysis model from the sessions' summaries and
approved cross-table findings, stored here as JSON, and printed after the
executive summary when the assembly has at least two sessions.
"""
import sqlalchemy as sa
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("assemblies") as batch:
        batch.add_column(sa.Column("synthesis_json", sa.Text(), nullable=True))
        batch.add_column(sa.Column("synthesis_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    with op.batch_alter_table("assemblies") as batch:
        batch.drop_column("synthesis_at")
        batch.drop_column("synthesis_json")
