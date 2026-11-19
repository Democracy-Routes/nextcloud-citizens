# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bulk approval of draft findings: the organizer's "approve all" and the
server's own approval of a Record now session (services/auto_organized.py)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from citizens.db.models import Finding, Round
from citizens.db.models.base import utcnow
from citizens.services.audit import record_audit_event

#: reviewed_by of a finding the server approved itself
AUTO_REVIEWER = "system:auto"


def approve_drafts(
    session: Session, round_: Round, *, actor: str,
    table_number: int | None = None, automatic: bool = False,
) -> int:
    """DRAFT -> APPROVED for a round, or one of its tables. Only drafts: a
    REJECTED finding is somebody's decision and is never reversed in bulk.
    Returns how many were approved."""
    query = select(Finding).where(Finding.round_id == round_.id, Finding.status == "DRAFT")
    if table_number is not None:
        table_ids = [t.id for t in round_.tables if t.number == table_number]
        query = query.where(Finding.table_id.in_(table_ids))
    reviewer = AUTO_REVIEWER if automatic else actor
    now = utcnow()
    approved = 0
    for finding in list(session.execute(query).scalars()):
        finding.status = "APPROVED"
        finding.reviewed_by = reviewer
        finding.reviewed_at = now
        approved += 1
        # one row per finding, as the single-finding path writes: it is what
        # makes an individual finding's review history reconstructable
        data = {"status": "APPROVED", "edited": False, "bulk": True}
        if automatic:
            data["automatic"] = True
        record_audit_event(session, "finding_reviewed", "finding", finding.id, actor=reviewer, data=data)
    session.flush()
    return approved
