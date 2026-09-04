# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""names to keep out of the analysis prompt

Revision ID: 0018
Revises: 0017
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Empty by default: redaction uses the imported roster plus whatever the
    # organizer adds here, and inventing names for existing assemblies would be
    # a guess about people we know nothing about.
    with op.batch_alter_table("assemblies") as batch:
        batch.add_column(
            sa.Column("redact_names", sa.Text(), nullable=False, server_default="")
        )


def downgrade() -> None:
    with op.batch_alter_table("assemblies") as batch:
        batch.drop_column("redact_names")
