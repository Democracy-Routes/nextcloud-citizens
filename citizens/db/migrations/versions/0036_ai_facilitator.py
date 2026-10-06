# SPDX-License-Identifier: AGPL-3.0-or-later
"""The AI facilitator (0.7): per-assembly level, per-table override, what it
said and what people thought of it.

- assemblies.ai_facilitator: off / light / normal / active, NULL = the
  instance default from Settings.
- table_facilitation: a table's own switch (from the table's phone or the
  Live tab's "Pause AI"), overriding the assembly's level.
- facilitator_interventions: every piece of advice the model produced, to
  whom it went (the facilitator's phone, or the table's phones when none is
  connected), the message it became, and the caption position it had read.
- facilitator_feedback: the thumbs under an intervention, from the table's
  phone or the facilitator's — never mixed with anything else.
"""
import sqlalchemy as sa
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("assemblies") as batch:
        batch.add_column(sa.Column("ai_facilitator", sa.String(12), nullable=True))
    op.create_table(
        "table_facilitation",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "assembly_id", sa.String(36), sa.ForeignKey("assemblies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("table_number", sa.Integer, nullable=False),
        sa.Column("level", sa.String(12), nullable=False),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("assembly_id", "table_number", name="uq_table_facilitation"),
    )
    op.create_table(
        "facilitator_interventions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "assembly_id", sa.String(36), sa.ForeignKey("assemblies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "round_id", sa.String(36), sa.ForeignKey("rounds.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("table_number", sa.Integer, nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        # "facilitator" (the advice card on their phone) or "table" (a banner)
        sa.Column("delivered_to", sa.String(16), nullable=False),
        sa.Column("message_id", sa.Integer, nullable=True),
        sa.Column("facilitator_session_id", sa.String(36), nullable=True),
        # how far into the captions the model had read (seconds), so the next
        # tick counts only what was said since
        sa.Column("caption_t", sa.Float, nullable=True),
        sa.Column("model", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_to_table_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_facilitator_interventions_assembly_id", "facilitator_interventions", ["assembly_id"]
    )
    op.create_table(
        "facilitator_feedback",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "intervention_id", sa.String(36),
            sa.ForeignKey("facilitator_interventions.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("table_number", sa.Integer, nullable=False),
        # "table_phone" or "facilitator"
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("helpful", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_facilitator_feedback_intervention_id", "facilitator_feedback", ["intervention_id"]
    )


def downgrade():
    op.drop_index("ix_facilitator_feedback_intervention_id", table_name="facilitator_feedback")
    op.drop_table("facilitator_feedback")
    op.drop_index(
        "ix_facilitator_interventions_assembly_id", table_name="facilitator_interventions"
    )
    op.drop_table("facilitator_interventions")
    op.drop_table("table_facilitation")
    with op.batch_alter_table("assemblies") as batch:
        batch.drop_column("ai_facilitator")
