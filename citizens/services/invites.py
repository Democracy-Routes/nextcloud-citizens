# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Table codes: the per-table QR invites an organizer prints (brief §13–§14).

A table code is one kind of capability (`RecorderInvite.purpose = JOIN_TABLE`):
reusable for thirty days, so a replacement phone can rescan the same poster.
The short-lived single-use action codes a phone makes for the next phone live
in services/capabilities.py on the same rows; everything here that lists,
prints, regenerates or re-materialises codes is about the printed table codes
only, and filters by purpose.
"""

import io
from datetime import timedelta

import segno
from sqlalchemy import select
from sqlalchemy.orm import Session

from citizens.db.models import Assembly, RecorderInvite, RecorderSession
from citizens.db.models.base import utcnow
from citizens.domain import schemas
from citizens.logging_setup import get_logger
from citizens.security.invite_vault import decrypt_token, encrypt_token
from citizens.security.recorder_tokens import generate_token, hash_token
from citizens.services.public_url import recorder_page_url

log = get_logger(__name__)

# How long a printed QR code stays valid. Long enough for an independent-mode
# assembly whose tables record days apart, and for participants to come back to
# a published report; short enough that a photographed poster does not join an
# assembly months later. Regenerating the sheets resets the clock.
INVITE_LIFETIME_DAYS = 30

JOIN_TABLE = "JOIN_TABLE"


def recorder_join_url(token: str) -> str:
    """The URL a table phone opens. The token travels in the fragment so it
    never appears in server access logs; the recorder page exchanges it for a
    short-lived session. The page address comes from services/public_url —
    Nextcloud's public URL, not the address this container reaches it at."""
    return f"{recorder_page_url()}#/join/{token}"


def participant_register_url(token: str) -> str:
    """The URL a participant's own phone opens to register at a table
    (REGISTER_PARTICIPANT code): the same page, a different route, so the
    recorder app lands on the registration page rather than trying to join."""
    return f"{recorder_page_url()}#/register/{token}"


def qr_svg(url: str) -> str:
    """A QR code as a STANDALONE SVG document.

    Not svg_inline(): that serialises with svgns=False, which is correct only
    when the markup is pasted into an HTML page, where the parser supplies the
    SVG namespace. The organizer renders this in an <img> instead — safer,
    since an image cannot execute script whatever it contains — and an <img>
    parses its source as an independent XML document. Without the xmlns the
    root element is in no namespace, nothing recognises it as SVG, and the
    browser reports a decode failure: naturalWidth 0, a broken-image icon, and
    a QR sheet with no codes on it minutes before the doors open.

    The same trap is documented in qr_sheet.py, which hit it from the other
    side: fpdf2 also rejects a root element with no namespace.

    omitsize keeps the viewBox and drops width/height, so CSS scales the code
    without clipping it — the <img> must therefore be given a size.
    """
    buffer = io.BytesIO()
    segno.make(url, error="m").save(
        buffer, kind="svg", scale=4, dark="#000000", omitsize=True, xmldecl=False
    )
    return buffer.getvalue().decode()


def _invite_card(table_number: int, token: str) -> schemas.InviteGenerated:
    url = recorder_join_url(token)
    return schemas.InviteGenerated(
        table_number=table_number,
        url=url,
        qr_svg=qr_svg(url),
    )


def generate_invites(session: Session, assembly: Assembly) -> list[schemas.InviteGenerated]:
    """Create fresh table codes for every table number, revoking the active ones.

    Join verification uses only the SHA-256 hash; the raw token is also kept
    encrypted with the app secret so the QR sheet can be re-viewed anytime.
    Action codes a phone made for the next phone are left alone: they are not
    on the sheet being replaced.
    """
    table_numbers = sorted(
        {table.number for round_ in assembly.rounds for table in round_.tables}
    ) or list(range(1, assembly.default_table_count + 1))

    now = utcnow()
    for invite in _active_invites(session, assembly.id, purpose=JOIN_TABLE):
        invite.revoked_at = now

    generated = [issue_invite(session, assembly, number, now=now) for number in table_numbers]
    session.flush()
    return generated


def issue_invite(
    session: Session, assembly: Assembly, table_number: int, now=None
) -> schemas.InviteGenerated:
    """One fresh table code for one table, leaving every other table's code alone.

    This is what a table added mid-event gets: the sheet already on the wall
    stays valid, and only the new table has a code to print.
    """
    now = now or utcnow()
    token = generate_token()
    session.add(
        RecorderInvite(
            assembly_id=assembly.id,
            purpose=JOIN_TABLE,
            table_number=table_number,
            token_hash=hash_token(token),
            token_encrypted=encrypt_token(token),
            expires_at=now + timedelta(days=INVITE_LIFETIME_DAYS),
        )
    )
    return _invite_card(table_number, token)


def invite_links(session: Session, assembly: Assembly) -> list[schemas.InviteGenerated]:
    """Re-materialize the QR sheet for the currently active table codes.

    Invites issued before token storage existed (or under a different app
    secret) cannot be decrypted and are skipped — the UI falls back to a
    regenerate hint when the list comes back shorter than the active count.
    """
    cards: list[schemas.InviteGenerated] = []
    for invite in _active_invites(session, assembly.id, purpose=JOIN_TABLE):
        if not invite.token_encrypted or invite.table_number is None:
            continue
        token = decrypt_token(invite.token_encrypted)
        if token is None:
            continue
        cards.append(_invite_card(invite.table_number, token))
    cards.sort(key=lambda card: card.table_number)
    return cards


def session_invite_card(
    session: Session, recorder_session: RecorderSession
) -> schemas.InviteGenerated | None:
    """The join card for the invite THIS phone joined through, or None.

    Lets a plenary phone show the room's shared QR so the next phone joins by
    scanning it, with no trip to the organizer. None when the invite has since
    been revoked or expired, or its token cannot be decrypted (legacy invite,
    rotated app secret) — a dead QR on screen is worse than none.
    """
    invite = session.get(RecorderInvite, recorder_session.invite_id)
    if invite is None or invite.revoked_at is not None or invite.table_number is None:
        return None
    if invite.single_use and invite.consumed_at is not None:
        return None
    if invite.expires_at is not None and invite.expires_at <= utcnow():
        return None
    if not invite.token_encrypted:
        return None
    token = decrypt_token(invite.token_encrypted)
    if token is None:
        return None
    return _invite_card(invite.table_number, token)


def list_invites(session: Session, assembly_id: str) -> list[schemas.InviteOut]:
    invites = session.execute(
        select(RecorderInvite)
        .where(RecorderInvite.assembly_id == assembly_id, RecorderInvite.purpose == JOIN_TABLE)
        .order_by(RecorderInvite.table_number, RecorderInvite.created_at)
    ).scalars()
    latest: dict[int, RecorderInvite] = {}
    for invite in invites:
        latest[invite.table_number] = invite
    return [
        schemas.InviteOut(
            id=invite.id,
            table_number=invite.table_number,
            active=invite.revoked_at is None,
            created_at=invite.created_at,
        )
        for invite in latest.values()
    ]


def revoke_invites(session: Session, assembly_id: str) -> int:
    """Revoke all active invites AND disconnect the devices already using them.

    Revoking the invite alone left every phone that had already joined with a
    working bearer for the rest of its 16-hour lifetime: someone who
    photographed a table's QR poster kept uploading audio and reading the
    report long after the organizer believed they had been removed.

    Regenerating QR sheets deliberately does not do this (see generate_invites)
    — new codes should not knock live tables off mid-round.

    Every live session for the assembly is cut, not only those holding a
    currently-active invite. Regeneration marks the previous invites revoked
    while their sessions keep working (by design), so scoping this to active
    invites left exactly those devices connected — through the one action an
    organizer reaches for when they want everyone off now. Action codes a
    phone made are revoked too: "everyone off" includes whoever was about to
    scan one.
    """
    now = utcnow()
    active = _active_invites(session, assembly_id)
    for invite in active:
        invite.revoked_at = now
    live = session.execute(
        select(RecorderSession).where(
            RecorderSession.assembly_id == assembly_id,
            RecorderSession.revoked_at.is_(None),
        )
    ).scalars()
    disconnected = 0
    for recorder_session in live:
        recorder_session.revoked_at = now
        disconnected += 1
    log.info(
        "invites_revoked",
        assembly_id=assembly_id, invites=len(active), devices_disconnected=disconnected,
    )
    session.flush()
    return len(active)


def find_by_token(session: Session, token: str) -> RecorderInvite | None:
    """The invite behind a token, whatever its state. Callers decide what a
    revoked, expired or consumed one means to them."""
    return session.execute(
        select(RecorderInvite).where(RecorderInvite.token_hash == hash_token(token))
    ).scalar_one_or_none()


def is_expired(invite: RecorderInvite, now=None) -> bool:
    return invite.expires_at is not None and invite.expires_at < (now or utcnow())


def find_active_by_token(session: Session, token: str) -> RecorderInvite | None:
    invite = find_by_token(session, token)
    if invite is None or invite.revoked_at is not None:
        return None
    if invite.single_use and invite.consumed_at is not None:
        return None
    if is_expired(invite):
        log.info("invite_expired", assembly_id=invite.assembly_id,
                 table_number=invite.table_number, purpose=invite.purpose)
        return None
    return invite


def active_invite_for_table(
    session: Session, assembly_id: str, table_number: int
) -> RecorderInvite | None:
    """The newest active table code for one table, or None."""
    return session.execute(
        select(RecorderInvite)
        .where(
            RecorderInvite.assembly_id == assembly_id,
            RecorderInvite.purpose == JOIN_TABLE,
            RecorderInvite.table_number == table_number,
            RecorderInvite.revoked_at.is_(None),
        )
        .order_by(RecorderInvite.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _active_invites(
    session: Session, assembly_id: str, purpose: str | None = None
) -> list[RecorderInvite]:
    query = select(RecorderInvite).where(
        RecorderInvite.assembly_id == assembly_id,
        RecorderInvite.revoked_at.is_(None),
    )
    if purpose is not None:
        query = query.where(RecorderInvite.purpose == purpose)
    return list(session.execute(query).scalars())
