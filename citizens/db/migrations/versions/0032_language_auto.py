# SPDX-License-Identifier: AGPL-3.0-or-later
"""assemblies.language_auto — Record now follows the language that was spoken.

"Record now" takes the organizer's UI language because there is no form to
ask; an Italian table under an English Nextcloud got an English report. When
this flag is set the final transcription is asked to detect the language and
the first detected one becomes the container's language — so analysis and
the report come out in the language people spoke. Wizards, which have a
language picker, leave it off; choosing a language by hand clears it.
"""
import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("assemblies") as batch:
        batch.add_column(
            sa.Column("language_auto", sa.Boolean(), nullable=False, server_default="0")
        )


def downgrade():
    with op.batch_alter_table("assemblies") as batch:
        batch.drop_column("language_auto")
