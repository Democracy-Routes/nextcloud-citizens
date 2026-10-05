# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""API request/response schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RoundIn(BaseModel):
    title: str = ""
    question: str = ""
    # what the discussion should produce, as distinct from what it is about
    objective: str | None = Field(default=None, max_length=2000)
    duration_minutes: int = Field(default=30, ge=1, le=600)


class RoundUpdate(BaseModel):
    title: str | None = None
    question: str | None = None
    # sent as "" to clear; left out to keep (see assemblies.update_round)
    objective: str | None = Field(default=None, max_length=2000)
    duration_minutes: int | None = Field(default=None, ge=1, le=600)
    position: int | None = Field(default=None, ge=1)


class RoundOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    position: int
    title: str
    question: str
    objective: str | None = None
    duration_minutes: int
    status: str
    started_at: datetime | None
    ended_at: datetime | None
    # so the delete dialog can say how many recordings it is about to destroy
    # rather than "any recordings made in it"
    recording_count: int = 0


#: The languages the organizer can choose. Anything else reaches the analysis
#: prompt as "English" and picks no transcription model for the room's actual
#: language, so it is refused rather than accepted and quietly ignored.
Language = Literal["en", "it", "de", "fr", "es"]


class AssemblyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    language: Language = "en"
    scheduled_at: datetime | None = None
    recording_mode: Literal["orchestrated", "independent", "plenary"] = "orchestrated"
    expected_participants: int = Field(default=0, ge=0, le=10000)
    # At least one: with zero tables no Table rows are built, so no QR codes are
    # generated and no phone can ever join. Nothing in the UI can repair that
    # afterwards - raising the count creates tables only for FUTURE rounds - so
    # the assembly has to be deleted and made again.
    default_table_count: int = Field(default=1, ge=1, le=200)
    analysis_instructions: str = Field(default="", max_length=4000)
    auto_purge_device_audio: bool = True
    redact_names: str = Field(default="", max_length=2000)
    # 'required': a table records only once one registered person there has
    # consented (services/consent.py). The organizer's wizard sends 'required'
    # for an organized assembly; the API default stays 'optional' so clients
    # and scripts from before 0.7 keep working unchanged.
    participant_consent: Literal["required", "optional"] = "optional"
    rounds: list[RoundIn] = []


class AssemblyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    language: Language | None = None
    scheduled_at: datetime | None = None
    recording_mode: Literal["orchestrated", "independent", "plenary"] | None = None
    expected_participants: int | None = Field(default=None, ge=0, le=10000)
    default_table_count: int | None = Field(default=None, ge=1, le=200)
    analysis_instructions: str | None = Field(default=None, max_length=4000)
    auto_purge_device_audio: bool | None = None
    redact_names: str | None = Field(default=None, max_length=2000)
    # null follows the instance default; 0 keeps audio indefinitely
    audio_retention_days: int | None = Field(default=None, ge=0, le=3650)
    participant_consent: Literal["required", "optional"] | None = None
    # false when the organizer picks the language by hand on a Record-now session
    language_auto: bool | None = None


class AssemblyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    # "assembly" for an organized event; "session" for the container behind a
    # standalone Session, which the UI lists as a Session and never as an assembly
    kind: str = "assembly"
    name: str
    description: str
    language: str
    scheduled_at: datetime | None
    status: str
    recording_mode: str
    expected_participants: int
    default_table_count: int
    analysis_instructions: str
    auto_purge_device_audio: bool
    redact_names: str
    closed_at: datetime | None
    audio_retention_days: int | None = None
    audio_purged_at: datetime | None = None
    participant_consent: str = "optional"
    # the language is being detected from the recording (Record now)
    language_auto: bool = False
    created_by: str
    created_at: datetime


class AssemblyDetail(AssemblyOut):
    rounds: list[RoundOut]
    participant_count: int = 0


class ParticipantIn(BaseModel):
    label: str = Field(min_length=1, max_length=50)
    name: str = ""
    email: str = ""
    notes: str = ""


class ParticipantsBulkIn(BaseModel):
    participants: list[ParticipantIn]


class CsvImportIn(BaseModel):
    csv: str


class ParticipantConsentOut(BaseModel):
    """A person's newest consent act, as recorded at the table."""

    method: str
    notice_version: str
    notice_hash: str
    notice_language: str
    notice_read: bool
    recording: bool
    transcription: bool
    analysis: bool
    publication: bool
    confirmed_at: datetime
    withdrawn_at: datetime | None = None


class ParticipantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    label: str
    name: str
    email: str
    notes: str
    # ORGANIZER, TABLE_DEVICE or SELF_PHONE — where the row came from
    source: str = "ORGANIZER"
    registered_table_number: int | None = None
    consent: ParticipantConsentOut | None = None


class TableOut(BaseModel):
    id: str
    # the identity, unique within the assembly; printed on the QR sheet
    number: int
    # a visual cue only — blue, green, orange, purple, red, teal, then blue again
    color_key: str = ""
    label: str
    status: str
    participants: list[ParticipantOut]


class AssignmentMove(BaseModel):
    participant_id: str
    to_table_id: str


class InviteOut(BaseModel):
    id: str
    table_number: int
    active: bool
    created_at: datetime


class InviteGenerated(BaseModel):
    table_number: int
    url: str
    qr_svg: str


class TableAdded(BaseModel):
    """A table added to a running assembly or Session: its number and colour
    (the same in every round), and the QR code that joins a phone to it."""

    number: int
    color_key: str
    invite: InviteGenerated


class AssemblyCreated(AssemblyDetail):
    # QR invites generated by default at creation; raw links appear ONLY here
    # (hash-only storage — regenerate to obtain new ones later)
    invites: list[InviteGenerated] = []


class SessionCreate(BaseModel):
    """A Session on its own: no assembly to name, configure or understand first.

    Question and objective are the whole brief; the rest are the defaults the
    assembly wizard also offers. Infrastructure settings are deliberately not
    here — they belong to the instance, not to a Session.
    """

    question: str = Field(default="", max_length=2000)
    objective: str | None = Field(default=None, max_length=2000)
    duration_minutes: int = Field(default=30, ge=1, le=600)
    table_count: int = Field(default=1, ge=1, le=200)
    recording_mode: Literal["orchestrated", "independent", "plenary"] = "orchestrated"
    language: Language = "en"


class SessionCreated(BaseModel):
    # the Session's own id — the id every /rounds/{id} route accepts today
    session_id: str
    # the container behind it; the organizer screens are reached through it
    # (see services/sessions.py for why it exists at all)
    container_id: str
    question: str
    objective: str | None
    recording_mode: str
    table_count: int
    # raw QR links appear only in this response, as for assemblies
    invites: list[InviteGenerated]


class SessionTableOut(BaseModel):
    id: str
    number: int
    color_key: str


class SessionOut(BaseModel):
    """A Session in product vocabulary — the adapter over a Round.

    `session_id` is the round's id and works on every `/rounds/{id}` route;
    `container_id` is the assembly behind it, `standalone` whether that
    container is the synthetic one a standalone Session lives in.
    """

    session_id: str
    container_id: str
    container_name: str
    standalone: bool
    position: int
    title: str
    question: str
    objective: str | None
    duration_minutes: int
    status: str
    recording_mode: str
    language: str
    started_at: datetime | None
    ended_at: datetime | None
    tables: list[SessionTableOut]
    recording_count: int = 0


class MessageIn(BaseModel):
    """What the organizer says to the tables. Presets (TIME_LEFT with
    minutes, WRAP_UP) are worded by the server in the assembly's language;
    PROMPT and CUSTOM carry their own text."""

    kind: Literal["TIME_LEFT", "WRAP_UP", "PROMPT", "CUSTOM"]
    text: str | None = Field(default=None, max_length=300)
    minutes: int | None = Field(default=None, ge=1, le=600)
    target_table_number: int | None = Field(default=None, ge=1)
    sound: bool = False


class MessageOut(BaseModel):
    id: int
    kind: str
    text: str
    sound: bool
    created_at: datetime
    created_by: str | None = None
    target_table_number: int | None = None
    seen_by: list[int] = []
    not_seen_by: list[int] = []


class MessageSeenIn(BaseModel):
    message_id: int = Field(ge=1)


class PromoteSessionIn(BaseModel):
    """A standalone Session becomes an Assembly: the event needs a name."""

    name: str = Field(min_length=1, max_length=200)


class PromotedOut(BaseModel):
    container_id: str
    kind: str
    name: str


class RecordNowIn(BaseModel):
    language: Language = "en"


class RecordNowOut(BaseModel):
    session_id: str
    container_id: str
    table_number: int
    # the recorder page with Table 1's join token in the fragment: opening it
    # on this very device makes it the Session's first recorder
    recorder_url: str
