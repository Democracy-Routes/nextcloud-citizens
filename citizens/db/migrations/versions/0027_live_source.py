# SPDX-License-Identifier: AGPL-3.0-or-later
"""recordings.live_source — the one recording per table that feeds live captions.

A table may have several recorder phones (0.7). Every one of them records and
uploads, and every recording is transcribed afterwards; but only ONE should
drive the live captions — otherwise the room pays for N streaming sessions,
sees N competing caption feeds, and a future facilitator would be handed two
versions of the same minute. `live_source` marks that recording. The partial
unique index makes two primaries at one table impossible, whatever the code
does: at most one row per (round, table) may carry the flag.

A phone can be promoted, and the flag moves when its holder stops recording
(completed, replaced, gone silent) to a sibling still recording, if any.

Existing data: whatever is RECORDING right now was feeding captions before
this migration, so the newest recording per table that is still RECORDING is
marked as the source — captions do not stop mid-round because of an upgrade.
"""
import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("recordings") as batch:
        batch.add_column(
            sa.Column("live_source", sa.Boolean(), nullable=False, server_default="0")
        )
    op.execute(
        "UPDATE recordings SET live_source = 1 WHERE state = 'RECORDING' AND id = ("
        "  SELECT r2.id FROM recordings r2"
        "  WHERE r2.round_id = recordings.round_id AND r2.table_id = recordings.table_id"
        "    AND r2.state = 'RECORDING'"
        "  ORDER BY r2.created_at DESC LIMIT 1)"
    )
    op.create_index(
        "uq_recordings_live_source_per_table",
        "recordings",
        ["round_id", "table_id"],
        unique=True,
        sqlite_where=sa.text("live_source = 1"),
    )


def downgrade():
    op.drop_index("uq_recordings_live_source_per_table", table_name="recordings")
    with op.batch_alter_table("recordings") as batch:
        batch.drop_column("live_source")
