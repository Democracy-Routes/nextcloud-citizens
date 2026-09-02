# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""assemblies.device_audio_purge_requested_at — clear the table phones

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable, no default: NULL means the organizer has never asked for the
    # phones to be cleared, which is true of every existing assembly.
    with op.batch_alter_table("assemblies") as batch:
        batch.add_column(
            sa.Column("device_audio_purge_requested_at", sa.DateTime(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("assemblies") as batch:
        batch.drop_column("device_audio_purge_requested_at")
