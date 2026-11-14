# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Seed provenance (0.9): the excerpt a Polis statement rests on, the segment
it came from, and the critic's scores, written by the ground → draft →
critique pipeline so the organizer can judge a statement in one look.
Additive, nullable, no data copied.

Revision ID: 0042
Revises: 0041
"""

import sqlalchemy as sa
from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("statement_seeds") as batch:
        batch.add_column(sa.Column("evidence_text", sa.Text(), nullable=True))
        batch.add_column(sa.Column("evidence_segment_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("quality_json", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("statement_seeds") as batch:
        batch.drop_column("quality_json")
        batch.drop_column("evidence_segment_id")
        batch.drop_column("evidence_text")
