# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""auto-purge device audio when the session closes

Revision ID: 0017
Revises: 0016
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Default true, including for assemblies that already exist: the guarantee
    # is on the phone (it deletes only audio the server has confirmed and keeps
    # everything else), and closing is the point at which leaving a citizen's
    # own device holding the recording stops being useful.
    with op.batch_alter_table("assemblies") as batch:
        batch.add_column(
            sa.Column(
                "auto_purge_device_audio",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("assemblies") as batch:
        batch.drop_column("auto_purge_device_audio")
