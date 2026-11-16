# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Session revocation (0.9): participant sessions can be revoked (so "revoke
all invites" cuts them too) and standalone accounts carry a session
generation that every cookie must match (password change, sign-out
everywhere and role changes invalidate older cookies). Additive, nullable.

Revision ID: 0043
Revises: 0042
"""

import sqlalchemy as sa
from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("participant_sessions") as batch:
        batch.add_column(sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("app_users") as batch:
        batch.add_column(sa.Column("session_generation", sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table("app_users") as batch:
        batch.drop_column("session_generation")
    with op.batch_alter_table("participant_sessions") as batch:
        batch.drop_column("revoked_at")
