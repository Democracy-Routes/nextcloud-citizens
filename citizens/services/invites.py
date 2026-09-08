# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Recorder invites: per assembly+table QR tokens (brief §13–§14)."""

import io
from datetime import timedelta

import segno
from sqlalchemy import select
from sqlalchemy.orm import Session

from citizens.config import get_settings
from citizens.db.models import Assembly, RecorderInvite, RecorderSession
from citizens.db.models.base import utcnow
from citizens.domain import schemas
from citizens.logging_setup import get_logger
from citizens.security.invite_vault import decrypt_token, encrypt_token
from citizens.security.recorder_tokens import generate_token, hash_token

log = get_logger(__name__)

# How long a printed QR code stays valid. Long enough for an independent-mode
# assembly whose tables record days apart, and for participants to come back to
# a published report; short enough that a photographed poster does not join an
# assembly months later. Regenerating the sheets resets the clock.
INVITE_LIFETIME_DAYS = 30


def recorder_join_url(token: str) -> str:
    """The URL a table phone opens. The token travels in the fragment so it
    never appears in server access logs; the recorder page exchanges it for a
    short-lived session. The path MUST end in .html — that's what makes the
    AppAPI proxy inject its CSP nonce into the page's scripts."""
    base = get_settings().nextcloud_url.rstrip("/")
    return f"{base}/index.php/apps/app_api/proxy/citizens/recorder.html#/join/{token}"


def _qr_svg(url: str) -> str:
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
        qr_svg=_qr_svg(url),
    )


def generate_invites(session: Session, assembly: Assembly) -> list[schemas.InviteGenerated]:
    """Create fresh invites for every table number, revoking any active ones.

    Join verification uses only the SHA-256 hash; the raw token is also kept
    encrypted with the app secret so the QR sheet can be re-viewed anytime.
    """
    table_numbers = sorted(
        {table.number for round_ in assembly.rounds for table in round_.tables}
    ) or list(range(1, assembly.default_table_count + 1))

    now = utcnow()
    for invite in _active_invites(session, assembly.id):
        invite.revoked_at = now

    generated: list[schemas.InviteGenerated] = []
    for number in table_numbers:
        token = generate_token()
        session.add(
            RecorderInvite(
                assembly_id=assembly.id,
                table_number=number,
                token_hash=hash_token(token),
                token_encrypted=encrypt_token(token),
                expires_at=now + timedelta(days=INVITE_LIFETIME_DAYS),
            )
        )
        generated.append(_invite_card(number, token))
    session.flush()
    return generated


def invite_links(session: Session, assembly: Assembly) -> list[schemas.InviteGenerated]:
    """Re-materialize the QR sheet for the currently active invites.

    Invites issued before token storage existed (or under a different app
    secret) cannot be decrypted and are skipped — the UI falls back to a
    regenerate hint when the list comes back shorter than the active count.
    """
    cards: list[schemas.InviteGenerated] = []
    for invite in _active_invites(session, assembly.id):
        if not invite.token_encrypted:
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
    if invite is None or invite.revoked_at is not None:
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
        .where(RecorderInvite.assembly_id == assembly_id)
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
    organizer reaches for when they want everyone off now.
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


def find_active_by_token(session: Session, token: str) -> RecorderInvite | None:
    invite = session.execute(
        select(RecorderInvite).where(RecorderInvite.token_hash == hash_token(token))
    ).scalar_one_or_none()
    if invite is None or invite.revoked_at is not None:
        return None
    if invite.expires_at is not None and invite.expires_at < utcnow():
        log.info("invite_expired", assembly_id=invite.assembly_id,
                 table_number=invite.table_number)
        return None
    return invite


def _active_invites(session: Session, assembly_id: str) -> list[RecorderInvite]:
    return list(
        session.execute(
            select(RecorderInvite).where(
                RecorderInvite.assembly_id == assembly_id,
                RecorderInvite.revoked_at.is_(None),
            )
        ).scalars()
    )
