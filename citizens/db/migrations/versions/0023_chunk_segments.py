# SPDX-License-Identifier: AGPL-3.0-or-later
"""audio_chunks.segment_number — which MediaRecorder session a chunk came from.

A recording interrupted mid-round (screen off on an iPhone, a phone call) and
resumed on the same phone used to be two recordings. It is one now: the phone
keeps the sequence going and starts a new MediaRecorder, whose first chunk
carries a fresh container header. Concatenating that mid-stream is not
decodable audio, so assembly needs to know where each session starts — it
remuxes every segment on its own and joins them.

Everything recorded before this migration is one session: segment 0.
"""
import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("audio_chunks") as batch:
        batch.add_column(
            sa.Column("segment_number", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade():
    with op.batch_alter_table("audio_chunks") as batch:
        batch.drop_column("segment_number")
