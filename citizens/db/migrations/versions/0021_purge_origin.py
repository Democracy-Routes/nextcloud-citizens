# SPDX-License-Identifier: AGPL-3.0-or-later
"""assemblies.purge_requested_automatically — who asked the phones to delete.

Reopening an assembly must withdraw an automatic clear-the-phones request, but
not one the organizer asked for by hand. Until now the reopen keyed off the
auto_purge_device_audio toggle's CURRENT value, so toggling it off between
close and reopen left the standing request in place: every phone joining the
reopened assembly deleted each fresh recording the moment it reached
AUDIO_READY, with the organizer having explicitly disabled automatic purging.
"""
import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("assemblies") as batch:
        batch.add_column(
            sa.Column("purge_requested_automatically", sa.Boolean(), nullable=True)
        )
    # Every request that predates provenance is treated as withdrawable on
    # reopen (True). This is the safety-biased reading, and it is the ONLY one
    # that reaches the rows this column exists for: an assembly that was
    # auto-closed, had the toggle flipped off, and was reopened under the old
    # code sits open with its automatic request still standing — the bug's own
    # victims. Reading "open + standing = the organizer pressed the button"
    # would backfill exactly those rows as manual, cement the request forever
    # (close_assembly never reclassifies a standing one), and every phone
    # joining would keep deleting each fresh recording. Mislabelling a genuine
    # manual request costs one reopen withdrawing it — fewer deletes, never
    # more. Written as a portable boolean, not a SQLite integer literal.
    assemblies = sa.table(
        "assemblies",
        sa.column("purge_requested_automatically", sa.Boolean()),
        sa.column("device_audio_purge_requested_at", sa.DateTime()),
    )
    op.execute(
        sa.update(assemblies)
        .where(assemblies.c.device_audio_purge_requested_at.isnot(None))
        .values(purge_requested_automatically=True)
    )


def downgrade():
    with op.batch_alter_table("assemblies") as batch:
        batch.drop_column("purge_requested_automatically")
