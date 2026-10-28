# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Standalone mode (0.9): settings, accounts and account tokens of an
instance that runs without Nextcloud. Unused, and empty, in Nextcloud mode.

- app_config: the Settings values (sensitive ones encrypted with APP_SECRET).
- app_users: organizers and administrators; `id` goes into
  assemblies.created_by.
- account_tokens: invitation and password-reset links, stored hashed.
"""
import sqlalchemy as sa
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "app_config",
        sa.Column("key", sa.String(120), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False, server_default=""),
        sa.Column("sensitive", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "app_users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(120), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("email", sa.String(254), nullable=True),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_hash", sa.String(300), nullable=True),
        sa.Column("role", sa.String(16), nullable=False, server_default="organizer"),
        sa.Column("language", sa.String(8), nullable=False, server_default="en"),
        sa.Column("oidc_issuer", sa.String(300), nullable=True),
        sa.Column("oidc_subject", sa.String(300), nullable=True),
        sa.Column("notify_opt_out", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("disabled", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_app_users_username", "app_users", ["username"], unique=True)
    op.create_index("ix_app_users_email", "app_users", ["email"], unique=True)
    op.create_table(
        "account_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id", sa.String(36),
            sa.ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("token_encrypted", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_account_tokens_user_id", "account_tokens", ["user_id"])
    op.create_index("ix_account_tokens_token_hash", "account_tokens", ["token_hash"], unique=True)


def downgrade():
    op.drop_index("ix_account_tokens_token_hash", table_name="account_tokens")
    op.drop_index("ix_account_tokens_user_id", table_name="account_tokens")
    op.drop_table("account_tokens")
    op.drop_index("ix_app_users_email", table_name="app_users")
    op.drop_index("ix_app_users_username", table_name="app_users")
    op.drop_table("app_users")
    op.drop_table("app_config")
