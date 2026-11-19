# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Record now closes and publishes by itself (0.9): a persistent flag on the
container (NULL reads as false) and the moment the server finished it.
Additive, nullable.

Revision ID: 0044
Revises: 0043
"""

import sqlalchemy as sa
from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("assemblies") as batch:
        batch.add_column(sa.Column("auto_organized", sa.Boolean(), nullable=True))
        batch.add_column(sa.Column("auto_finalized_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    with op.batch_alter_table("assemblies") as batch:
        batch.drop_column("auto_finalized_at")
        batch.drop_column("auto_organized")
