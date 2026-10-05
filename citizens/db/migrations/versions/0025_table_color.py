# SPDX-License-Identifier: AGPL-3.0-or-later
"""tables.color_key — a colour beside the number, so a room can find "the blue table".

The number stays the identity (unique per round, printed on the QR sheet,
carried by every phone and recording); the colour is a second visual cue,
assigned from a six-colour palette by number and repeating after six. Nothing
may depend on it for correctness. Existing tables get the same colour a new
table of their number would: blue, green, orange, purple, red, teal, blue…
"""
import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

PALETTE = ("blue", "green", "orange", "purple", "red", "teal")


def upgrade():
    with op.batch_alter_table("tables") as batch:
        batch.add_column(
            sa.Column("color_key", sa.String(length=16), nullable=False, server_default="")
        )
    cases = " ".join(
        f"WHEN {index} THEN '{color}'" for index, color in enumerate(PALETTE)
    )
    op.execute(
        f"UPDATE tables SET color_key = CASE (number - 1) % {len(PALETTE)} {cases} END "
        "WHERE color_key = ''"
    )


def downgrade():
    with op.batch_alter_table("tables") as batch:
        batch.drop_column("color_key")
