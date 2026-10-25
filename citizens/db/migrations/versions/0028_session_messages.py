# SPDX-License-Identifier: AGPL-3.0-or-later
"""session_messages — what the organizer says to the tables, and who has seen it.

A facilitator at the front of the room has no way to tell twenty tables
"five minutes left" short of shouting. A message is written once, scoped to
a session (round) and optionally to one table, and rides the status poll every
phone already makes; the phone reports the newest id it has shown, so the Live
tab can say "delivered 9/10 · Table 7 offline". Integer ids on purpose: "newer
than what this phone saw" is then a comparison, not a join.

`recorder_sessions.last_seen_message_id` is the phone's receipt.
"""
import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "session_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "assembly_id", sa.String(36), sa.ForeignKey("assemblies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "round_id", sa.String(36), sa.ForeignKey("rounds.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("target_table_number", sa.Integer(), nullable=True),
        sa.Column("sound", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.create_index("ix_session_messages_round_id", "session_messages", ["round_id"])
    with op.batch_alter_table("recorder_sessions") as batch:
        batch.add_column(sa.Column("last_seen_message_id", sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table("recorder_sessions") as batch:
        batch.drop_column("last_seen_message_id")
    op.drop_index("ix_session_messages_round_id", table_name="session_messages")
    op.drop_table("session_messages")
