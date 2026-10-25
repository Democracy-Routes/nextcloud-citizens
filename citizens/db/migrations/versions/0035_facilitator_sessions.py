# SPDX-License-Identifier: AGPL-3.0-or-later
"""facilitator_sessions — a facilitator's own phone beside a table (0.7).

The table's phone shows an "Add facilitator" code (FACILITATE_TABLE, reusable
for a few hours, like the registration code); the facilitator scans it and
their phone is handed a bearer, hashed here like a recorder's. With it the
phone shows the session's question and time, the table's consent state and
hand, the organizer's messages, and lets the facilitator write a prompt to
the table's phones, raise the table's hand, register for consent or turn the
phone into a second recorder. It never records and never joins a table's
recorder slot. Deleting the assembly deletes the sessions.
"""
import sqlalchemy as sa
from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "facilitator_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "assembly_id", sa.String(36), sa.ForeignKey("assemblies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("table_number", sa.Integer, nullable=False),
        sa.Column(
            "invite_id", sa.String(36),
            sa.ForeignKey("recorder_invites.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        # the newest organizer message this phone has shown (like a recorder's)
        sa.Column("last_seen_message_id", sa.Integer, nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_facilitator_sessions_assembly_id", "facilitator_sessions", ["assembly_id"]
    )


def downgrade():
    op.drop_index("ix_facilitator_sessions_assembly_id", table_name="facilitator_sessions")
    op.drop_table("facilitator_sessions")
