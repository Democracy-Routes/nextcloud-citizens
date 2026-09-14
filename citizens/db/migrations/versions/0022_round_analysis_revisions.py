# SPDX-License-Identifier: AGPL-3.0-or-later
"""rounds.analysis_input_revision / analysis_applied_revision — is the
cross-table clustering current?

A SUCCEEDED round job is not proof the clusters reflect what the organizer
sees now: rejecting or editing findings changes the model's input, and a
timestamp cannot say whether a run consumed that change — a job's updated_at
is stamped when the runner marks it done, after the model call, so a review
that landed mid-run looks older than the run that never saw it. Two counters
can: input bumps whenever the findings change, applied is set from the input
revision the run started from. Stale ⇔ input > applied.

Existing rounds start at 0/0 — current by definition, so nothing is re-run
on upgrade.
"""
import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("rounds") as batch:
        batch.add_column(
            sa.Column("analysis_input_revision", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("analysis_applied_revision", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade():
    with op.batch_alter_table("rounds") as batch:
        batch.drop_column("analysis_applied_revision")
        batch.drop_column("analysis_input_revision")
