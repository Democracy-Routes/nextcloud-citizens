# SPDX-License-Identifier: AGPL-3.0-or-later
"""assemblies.kind and rounds.objective — a Session can stand on its own.

Citizens 0.7 makes the Session (one question, its tables, their recordings)
the unit a user starts from; an Assembly becomes the optional container that
groups several Sessions into an event. The schema still spells that as
Assembly → Round, and every storage path, ownership check, retention sweep and
export is keyed by assembly_id — so a standalone Session is stored as a Round
inside a container assembly of `kind = "session"`, which the UI never presents
as an assembly. `kind` is what tells the two apart. Everything that exists
before this migration was created through the assembly wizard: "assembly".

`objective` is the second half of a Session's brief, kept apart from the
question ("How should local mobility improve?" versus "Produce three concrete
proposals"): analysis, reports and the future facilitation features read them
differently. Legacy rounds have none, and NULL must keep working everywhere.
"""
import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("assemblies") as batch:
        batch.add_column(
            sa.Column("kind", sa.String(length=16), nullable=False, server_default="assembly")
        )
    with op.batch_alter_table("rounds") as batch:
        batch.add_column(sa.Column("objective", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("rounds") as batch:
        batch.drop_column("objective")
    with op.batch_alter_table("assemblies") as batch:
        batch.drop_column("kind")
