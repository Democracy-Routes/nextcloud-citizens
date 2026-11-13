# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Polis bridge (0.9): the conversation an assembly's approved statements were
sent to, with its links and the time of the push; when the organizer put the
poll on the table phones; the statement count asked of the seeds generation;
and each statement's id in Polis. Additive, nullable, no data copied.
"""
import sqlalchemy as sa
from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None

ASSEMBLY_COLUMNS = (
    ("polis_conversation_id", sa.String(120)),
    ("polis_url", sa.String(500)),
    ("polis_moderation_url", sa.String(500)),
    ("polis_report_url", sa.String(500)),
    ("polis_pushed_at", sa.DateTime(timezone=True)),
    ("polis_published_at", sa.DateTime(timezone=True)),
    ("seeds_target", sa.Integer()),
)


def upgrade():
    with op.batch_alter_table("assemblies") as batch:
        for name, type_ in ASSEMBLY_COLUMNS:
            batch.add_column(sa.Column(name, type_, nullable=True))
    with op.batch_alter_table("statement_seeds") as batch:
        batch.add_column(sa.Column("polis_tid", sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table("statement_seeds") as batch:
        batch.drop_column("polis_tid")
    with op.batch_alter_table("assemblies") as batch:
        for name, _ in reversed(ASSEMBLY_COLUMNS):
            batch.drop_column(name)
