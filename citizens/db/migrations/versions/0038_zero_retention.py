# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Zero retention (0.7, S10): an assembly that keeps nothing but its report.

- assemblies.zero_retention: once closed and fully processed, the audio and
  the transcripts are deleted and a PDF of the frozen report is kept
  (services/zero_retention.py).
- assemblies.zero_retention_done_at: when that ran; reopening and changing
  the language are refused from then on.
"""
import sqlalchemy as sa
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("assemblies") as batch:
        batch.add_column(
            sa.Column("zero_retention", sa.Boolean, nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("zero_retention_done_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade():
    with op.batch_alter_table("assemblies") as batch:
        batch.drop_column("zero_retention_done_at")
        batch.drop_column("zero_retention")
