# SPDX-License-Identifier: AGPL-3.0-or-later
"""recorder_invites become capabilities; recorder_sessions get a slot.

A table's printed QR code is one kind of capability: "join this table", reusable
for thirty days, so a replacement phone can rescan the same poster. 0.7 adds
two more, chosen by a phone that has already joined and shown as a QR for the
next phone to scan — the scanner never decides what the code means:

  ADD_RECORDER_TO_TABLE  the scanner becomes another recorder of THIS table
  ADD_TABLE              the next table is created and the scanner is its
                         first recorder

The same row carries all three (one token mechanism, one join route, the same
hashing, vault, rate limit and brute-force protection), distinguished by
`purpose`. The new ones are short-lived and `single_use`: `consumed_at` is set
atomically by the first scan and a second scan is refused. `round_id` records
the Session a capability was made in; `table_number` is NULL for ADD_TABLE,
whose number is allocated when it is consumed. `created_by_session_id` is who
made it — kept as a plain id, not a foreign key, because recorder_sessions
already points at recorder_invites and a cycle helps nobody.

Every invite that exists before this migration is a table code: JOIN_TABLE,
reusable, not consumed.

`recorder_sessions.slot` numbers the recorders of one table: the phone that
scanned the table's own code is slot 1 (and so is a replacement that rescans
it — same role), a phone added through ADD_RECORDER_TO_TABLE gets the next
slot. Every session before this migration is slot 1.
"""
import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("recorder_invites") as batch:
        batch.add_column(
            sa.Column("purpose", sa.String(length=32), nullable=False, server_default="JOIN_TABLE")
        )
        batch.alter_column("table_number", existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column("round_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_recorder_invites_round_id_rounds", "rounds", ["round_id"], ["id"],
            ondelete="SET NULL",
        )
        batch.add_column(
            sa.Column("single_use", sa.Boolean(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("consumed_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("created_by_session_id", sa.String(length=36), nullable=True))
    with op.batch_alter_table("recorder_sessions") as batch:
        batch.add_column(sa.Column("slot", sa.Integer(), nullable=False, server_default="1"))


def downgrade():
    # table_number goes back to NOT NULL, which the ADD_TABLE capabilities
    # cannot satisfy: they are short-lived single-use codes, not records
    op.execute("DELETE FROM recorder_invites WHERE purpose != 'JOIN_TABLE'")
    with op.batch_alter_table("recorder_sessions") as batch:
        batch.drop_column("slot")
    with op.batch_alter_table("recorder_invites") as batch:
        batch.drop_column("created_by_session_id")
        batch.drop_column("consumed_at")
        batch.drop_column("single_use")
        batch.drop_constraint("fk_recorder_invites_round_id_rounds", type_="foreignkey")
        batch.drop_column("round_id")
        batch.alter_column("table_number", existing_type=sa.Integer(), nullable=False)
        batch.drop_column("purpose")
