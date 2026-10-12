# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Recordings the server finishes, and the audio a phone sends afterwards (0.7).

- recordings.closed_by: "silence" when the sweep finished a recording whose
  phone had sent nothing for five minutes, "organizer" when the Live tab's
  Finish did it. NULL for every recording a phone finished itself.
- recordings.finish_requested_at: the organizer asked this phone to finish;
  the phone does it on its next poll, the sweep does it for a phone that
  never answers.
- recordings.continued_from_id / continued_by_id: a phone that comes back
  after its recording was closed keeps uploading under the old id; the
  server stores that audio in a continuation recording of the same table
  and slot. late_seq_shift maps the phone's sequence numbers onto the
  continuation's (its chunk 0 may be a stored container header, counted in
  late_header_chunks, so the mid-stream clusters stay decodable).
- recordings.audio_added_at: when a closed recording's phone came back.
- recorder_sessions.device_id: the phone's own random id, so a single-use
  code scanned again by the SAME phone returns its session instead of 410.
"""
import sqlalchemy as sa
from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("recordings") as batch:
        batch.add_column(sa.Column("closed_by", sa.String(16), nullable=True))
        batch.add_column(sa.Column("finish_requested_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("audio_added_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("continued_from_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("continued_by_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("late_seq_shift", sa.Integer, nullable=True))
        batch.add_column(sa.Column("late_header_chunks", sa.Integer, nullable=True))
    with op.batch_alter_table("recorder_sessions") as batch:
        batch.add_column(sa.Column("device_id", sa.String(64), nullable=True))


def downgrade():
    with op.batch_alter_table("recorder_sessions") as batch:
        batch.drop_column("device_id")
    with op.batch_alter_table("recordings") as batch:
        batch.drop_column("late_header_chunks")
        batch.drop_column("late_seq_shift")
        batch.drop_column("continued_by_id")
        batch.drop_column("continued_from_id")
        batch.drop_column("audio_added_at")
        batch.drop_column("finish_requested_at")
        batch.drop_column("closed_by")
