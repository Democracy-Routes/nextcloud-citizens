# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the organizer says to the tables during a session (0.7)."""

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from citizens.db.models.base import Base, TZDateTime, utcnow

MESSAGE_KINDS = ("TIME_LEFT", "WRAP_UP", "PROMPT", "CUSTOM")


class SessionMessage(Base):
    __tablename__ = "session_messages"

    # integer on purpose: a phone reports the newest id it has shown, and
    # "unseen" is then every row above it
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assembly_id: Mapped[str] = mapped_column(ForeignKey("assemblies.id", ondelete="CASCADE"))
    round_id: Mapped[str] = mapped_column(ForeignKey("rounds.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))
    # the sentence the tables see, already in the assembly's language
    text: Mapped[str] = mapped_column(Text)
    # None: every table of the session
    target_table_number: Mapped[int | None] = mapped_column(Integer)
    # the phone may vibrate once when it shows the message
    sound: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
