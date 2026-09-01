# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""recordings.superseded_at — a table's phone was replaced mid-round

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable with no default: every existing recording predates device
    # replacement, and NULL is exactly "this was never superseded".
    with op.batch_alter_table("recordings") as batch:
        batch.add_column(sa.Column("superseded_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("recordings") as batch:
        batch.drop_column("superseded_at")
