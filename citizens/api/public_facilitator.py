# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public facilitator API (PUBLIC AppAPI routes; facilitator-session bearer).

A facilitator's own phone beside ONE table (services/facilitators.py): it
reads what the table's phones read, writes prompts to them, raises the
table's hand and makes codes for that table. It never records. GET/POST
only: the proxy forwards nothing else to public routes.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from citizens.db.models import FacilitatorSession
from citizens.db.session import get_db, get_read_db
from citizens.security.rate_limit import (
    CAPABILITY_LIMITER,
    HELP_LIMITER,
    JOIN_IP_LIMITER,
    JOIN_TOKEN_LIMITER,
    PROMPT_LIMITER,
    client_ip,
    token_key,
)
from citizens.services import facilitators as facilitator_svc
from citizens.services import messages as messages_svc

router = APIRouter(prefix="/public")

DB = Annotated[Session, Depends(get_db)]
ReadDB = Annotated[Session, Depends(get_read_db)]


def _bearer(authorization: str) -> str:
    scheme, _, bearer = authorization.partition(" ")
    if scheme.lower() != "bearer" or not bearer:
        raise HTTPException(status_code=401, detail="Missing facilitator token")
    return bearer.strip()


def get_facilitator(session: DB, authorization: Annotated[str, Header()] = "") -> FacilitatorSession:
    return facilitator_svc.by_bearer(session, _bearer(authorization))


def get_reading_facilitator(
    session: ReadDB, authorization: Annotated[str, Header()] = ""
) -> FacilitatorSession:
    """For the poll: no write lock, no last_seen write (the heartbeat does that)."""
    return facilitator_svc.by_bearer(session, _bearer(authorization))


Facilitator = Annotated[FacilitatorSession, Depends(get_facilitator)]
ReadingFacilitator = Annotated[FacilitatorSession, Depends(get_reading_facilitator)]


class FacilitateIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)


@router.post("/facilitate")
def facilitate(data: FacilitateIn, request: Request, session: DB):
    """The facilitator's phone redeems the table's FACILITATE_TABLE code. The
    token travels in the body like /join's, under /join's limits."""
    JOIN_TOKEN_LIMITER.check(token_key(data.token))
    JOIN_IP_LIMITER.check(client_ip(request))
    facilitator, bearer, _ = facilitator_svc.join(session, data.token)
    return {
        "facilitator_token": bearer,
        "expires_at": facilitator.expires_at,
        **facilitator_svc.status(session, facilitator),
    }


@router.get("/facilitator/status")
def facilitator_status(facilitator: ReadingFacilitator, session: ReadDB):
    return facilitator_svc.status(session, facilitator)


@router.post("/facilitator/heartbeat")
def facilitator_heartbeat(facilitator: Facilitator, session: DB):
    """This phone is still beside the table — the AI facilitator addresses a
    connected facilitator before the table's phones."""
    facilitator_svc.touch(facilitator)
    return {"ok": True}


@router.post("/facilitator/leave")
def facilitator_leave(facilitator: Facilitator, session: DB):
    facilitator_svc.leave(session, facilitator)
    return {"ok": True}


class MessageSeenIn(BaseModel):
    message_id: int = Field(ge=1)


@router.post("/facilitator/messages/seen")
def facilitator_message_seen(data: MessageSeenIn, facilitator: Facilitator, session: DB):
    messages_svc.mark_seen(session, facilitator, data.message_id)
    return {"ok": True}


class PromptIn(BaseModel):
    text: str = Field(min_length=1, max_length=messages_svc.MAX_TEXT)


@router.post("/facilitator/prompt", status_code=201)
def facilitator_prompt(data: PromptIn, facilitator: Facilitator, session: DB):
    """A prompt to this table's phones: the same banner as the organizer's
    messages, labelled as the facilitator's."""
    PROMPT_LIMITER.check(facilitator.id)
    return facilitator_svc.send_prompt(session, facilitator, data.text)


class HelpIn(BaseModel):
    kind: Literal["TECHNICAL", "ORGANIZER", "PROCESS"]


@router.post("/facilitator/help", status_code=201)
def facilitator_help(data: HelpIn, facilitator: Facilitator, session: DB):
    """The table's hand, raised from the facilitator's phone."""
    HELP_LIMITER.check(facilitator.id)
    return facilitator_svc.raise_hand(session, facilitator, data.kind)


class CodeIn(BaseModel):
    purpose: Literal["REGISTER_PARTICIPANT", "ADD_RECORDER_TO_TABLE"]


@router.post("/facilitator/codes", status_code=201)
def facilitator_code(data: CodeIn, facilitator: Facilitator, session: DB):
    """A code for this table from the facilitator's phone: register for
    consent, or add a recorder (this phone included — the recorder app takes
    over when it opens the link)."""
    CAPABILITY_LIMITER.check(facilitator.id)
    return facilitator_svc.make_code(session, facilitator, data.purpose).as_dict()
