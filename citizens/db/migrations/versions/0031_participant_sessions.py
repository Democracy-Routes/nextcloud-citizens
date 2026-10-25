# SPDX-License-Identifier: AGPL-3.0-or-later
"""participant_sessions — a person who registered on their own phone keeps a
page (0.7).

A table's notice screen can show a registration code; a person scans it,
registers on their own phone (method SELF_PHONE, the table known from the
code) and is handed a bearer, hashed here like a recorder's. With it their
phone shows where they are registered, what they consented to, and the
published report once the organizer publishes it — the seed of the 1.0
participant interface. Erasing the participant erases the session.
"""
import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "participant_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "participant_id", sa.String(36),
            sa.ForeignKey("participants.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "assembly_id", sa.String(36), sa.ForeignKey("assemblies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_participant_sessions_participant_id", "participant_sessions", ["participant_id"]
    )


def downgrade():
    op.drop_index("ix_participant_sessions_participant_id", table_name="participant_sessions")
    op.drop_table("participant_sessions")
