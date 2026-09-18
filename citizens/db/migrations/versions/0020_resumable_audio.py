# SPDX-License-Identifier: AGPL-3.0-or-later
"""Resumable audio parts and complete-recording verification."""
import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("recordings", sa.Column("audio_manifest_sha256", sa.String(64), nullable=True))
    op.add_column("recordings", sa.Column("audio_manifest_bytes", sa.Integer(), nullable=True))
    op.create_table(
        "audio_parts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("recording_id", sa.String(36), sa.ForeignKey("recordings.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("part_number", sa.Integer(), nullable=False),
        sa.Column("total_bytes", sa.Integer(), nullable=False),
        sa.Column("chunk_sha256", sa.String(64), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.UniqueConstraint("recording_id", "sequence_number", "part_number"),
    )
    op.create_index("ix_audio_parts_recording_id", "audio_parts", ["recording_id"])


def downgrade():
    op.drop_table("audio_parts")
    with op.batch_alter_table("recordings") as batch:
        batch.drop_column("audio_manifest_sha256")
        batch.drop_column("audio_manifest_bytes")
