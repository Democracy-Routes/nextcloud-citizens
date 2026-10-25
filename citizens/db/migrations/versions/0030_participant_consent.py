# SPDX-License-Identifier: AGPL-3.0-or-later
"""Individual participant consent, recorded at the table (0.7).

Until now the phone showed a table-level notice and stored nothing: the app
could not say who agreed to what, and a real assembly meant a pile of paper
forms. The lawful basis the project documents is explicit consent (GDPR Art.
6(1)(a) and 9(2)(a) — political opinions are special-category data), which
needs an individual, affirmative, versioned record:

- `consent_notices`: the exact text people saw, once per hash. A notice is
  rendered by the server from settings and the live data-handling facts and
  hashed as shown, so the record proves what was read, not what the code
  says today.
- `participant_consents`: one row per consent act — who, where (table,
  round, recorder phone), by which method, which notice, and the four
  explicit ticks. A refusal is stored too: it is a record, like the paper
  form's "I do not consent". Erasing the participant erases the row.
- `participants.source` and the `registered_*` columns say that a person
  registered from a table phone rather than the organizer's list, and at
  which table.
- `assemblies.participant_consent`: 'required' blocks recording at a table
  until one registered person there consents; 'optional' keeps today's
  behaviour. Existing rows become 'optional' so nothing already running is
  blocked by an upgrade; new organized assemblies are created 'required'.
"""
import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "consent_notices",
        sa.Column("hash", sa.String(64), primary_key=True),
        sa.Column("version", sa.String(16), nullable=False),
        sa.Column("language", sa.String(10), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "participant_consents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "assembly_id", sa.String(36), sa.ForeignKey("assemblies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "participant_id", sa.String(36),
            sa.ForeignKey("participants.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "round_id", sa.String(36), sa.ForeignKey("rounds.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("table_number", sa.Integer(), nullable=True),
        sa.Column("recorder_session_id", sa.String(36), nullable=True),
        sa.Column("method", sa.String(16), nullable=False),
        sa.Column(
            "notice_hash", sa.String(64), sa.ForeignKey("consent_notices.hash"), nullable=False
        ),
        sa.Column("notice_version", sa.String(16), nullable=False),
        sa.Column("notice_language", sa.String(10), nullable=False),
        sa.Column("notice_read", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("recording_consent", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("transcription_consent", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("analysis_consent", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("publication_consent", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_participant_consents_assembly_id", "participant_consents", ["assembly_id"]
    )
    op.create_index(
        "ix_participant_consents_participant_id", "participant_consents", ["participant_id"]
    )
    with op.batch_alter_table("participants") as batch:
        batch.add_column(
            sa.Column("source", sa.String(16), nullable=False, server_default="ORGANIZER")
        )
        batch.add_column(sa.Column("registered_table_number", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column(
                "registered_round_id", sa.String(36),
                sa.ForeignKey("rounds.id", ondelete="SET NULL"), nullable=True,
            )
        )
        batch.add_column(sa.Column("registered_session_id", sa.String(36), nullable=True))
    with op.batch_alter_table("assemblies") as batch:
        batch.add_column(
            sa.Column(
                "participant_consent", sa.String(16), nullable=False, server_default="optional"
            )
        )


def downgrade():
    with op.batch_alter_table("assemblies") as batch:
        batch.drop_column("participant_consent")
    with op.batch_alter_table("participants") as batch:
        batch.drop_column("registered_session_id")
        batch.drop_column("registered_round_id")
        batch.drop_column("registered_table_number")
        batch.drop_column("source")
    op.drop_index("ix_participant_consents_participant_id", table_name="participant_consents")
    op.drop_index("ix_participant_consents_assembly_id", table_name="participant_consents")
    op.drop_table("participant_consents")
    op.drop_table("consent_notices")
