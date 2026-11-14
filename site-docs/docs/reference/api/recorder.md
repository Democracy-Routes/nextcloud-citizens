# Recorder and participant (public)

The routes phones and participants call, authenticated by the bearer token of their session rather than by an organizer sign-in.

48 operations. Generated; do not edit.

### `POST` `/api/v1/public/capabilities/peek`

**Peek Capability**

What a code would do if scanned, without scanning it: the phone warns
about an accident (a third recorder, a phone switching tables) and lets
the person cancel before a single-use code is spent. Same rate limits as
/join; the token travels in the body, never in the path.

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `token` | string | yes | Token |
| `device_id` | string or null | no | Device Id |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/public/facilitate`

**Facilitate**

The facilitator's phone redeems the table's FACILITATE_TABLE code. The
token travels in the body like /join's, under /join's limits.

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `token` | string | yes | Token |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/public/facilitator/advice/{intervention_id}/dismiss`

**Dismiss Advice**

The facilitator judged the AI's advice not worth the table's attention.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `intervention_id` | path | string | yes |  |
| `authorization` | header | string | no |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/public/facilitator/advice/{intervention_id}/feedback`

**Advice Feedback**

A thumb on a piece of advice, from the facilitator's phone.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `intervention_id` | path | string | yes |  |
| `authorization` | header | string | no |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `helpful` | boolean | yes | Helpful |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/public/facilitator/advice/{intervention_id}/send`

**Send Advice**

The facilitator sends the AI's advice on to the table's phones, as
their own prompt.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `intervention_id` | path | string | yes |  |
| `authorization` | header | string | no |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 201 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/public/facilitator/codes`

**Facilitator Code**

A code for this table from the facilitator's phone: register for
consent, or add a recorder (this phone included — the recorder app takes
over when it opens the link).

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `authorization` | header | string | no |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `purpose` | string (`REGISTER_PARTICIPANT`, `ADD_RECORDER_TO_TABLE`) | yes | Purpose |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 201 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/public/facilitator/heartbeat`

**Facilitator Heartbeat**

This phone is still beside the table — the AI facilitator addresses a
connected facilitator before the table's phones.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `authorization` | header | string | no |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/public/facilitator/help`

**Facilitator Help**

The table's hand, raised from the facilitator's phone.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `authorization` | header | string | no |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `kind` | string (`TECHNICAL`, `ORGANIZER`, `PROCESS`) | yes | Kind |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 201 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/public/facilitator/leave`

**Facilitator Leave**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `authorization` | header | string | no |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/public/facilitator/messages/seen`

**Facilitator Message Seen**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `authorization` | header | string | no |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `message_id` | integer | yes | Message Id |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/public/facilitator/prompt`

**Facilitator Prompt**

A prompt to this table's phones: the same banner as the organizer's
messages, labelled as the facilitator's.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `authorization` | header | string | no |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `text` | string | yes | Text |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 201 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/public/facilitator/status`

**Facilitator Status**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `authorization` | header | string | no |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/public/join`

**Join**

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `token` | string | yes | Token |
| `device_id` | string or null | no | Device Id |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/public/participant/report`

**Participant Report**

The published report, the same payload the table phones read.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `authorization` | header | string | no |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/public/participant/report.pdf`

**Participant Report Pdf**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `authorization` | header | string | no |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/public/participant/status`

**Participant Status**

The person's own page: where they registered, their consent, whether
the report is out, whom to contact to withdraw.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `authorization` | header | string | no |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/public/participant/validate`

**Participant Validate**

"Does this reflect your table?" — once the report is out. One answer per
person and session; a second tap replaces the first.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `authorization` | header | string | no |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `round_id` | string | yes | Round Id |
| `verdict` | string (`LOOKS_RIGHT`, `MISSING`) | yes | Verdict |
| `note` | string | no | Note |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/public/recorder/capabilities`

**Create Capability**

A joined phone makes a QR code for the next phone — add a recorder to
this table, or add a new table. The code means exactly that; the phone
that scans it does not choose.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `authorization` | header | string | no |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `purpose` | string (`ADD_RECORDER_TO_TABLE`, `ADD_TABLE`, `REGISTER_PARTICIPANT`, `FACILITATE_TABLE`) | yes | Purpose |
| `round_id` | string or null | no | Round Id |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 201 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/public/recorder/consent-notice`

**Consent Notice**

The notice people read before registering, rendered by the server and
hashed as shown, with this table's roster (names, never email) and the
assembly's rule (required / optional).

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `authorization` | header | string | no |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/public/recorder/facilitator`

**Set Facilitator Level**

The table's own AI-facilitator switch (tech sheet): a level of its
own, or "default" to follow the assembly again.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `authorization` | header | string | no |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `level` | string (`default`, `off`, `light`, `normal`, `active`) | yes | Level |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/public/recorder/heartbeat`

**Heartbeat**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `authorization` | header | string | no |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `recording_id` | string or null | no | Recording Id |
| `recording_active` | boolean | no | Recording Active |
| `armed` | boolean | no | Armed |
| `local_chunks` | integer | no | Local Chunks |
| `acked_chunks` | integer | no | Acked Chunks |
| `storage_ok` | boolean | no | Storage Ok |
| `storage_free_mb` | number or null | no | Storage Free Mb |
| `local_recordings` | integer or null | no | Local Recordings |
| `battery_level` | number or null | no | Battery Level |
| `visible` | boolean or null | no | Visible |
| `capture_ok` | boolean or null | no | Capture Ok |
| `screen_awake` | boolean or null | no | Screen Awake |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/public/recorder/help`

**Need Help**

The table raises its hand. One open request per table — tapping again
changes what it asks for. The Live tab shows it beside the table's
number; the phone learns of the acknowledgement on its status poll.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `authorization` | header | string | no |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `kind` | string (`TECHNICAL`, `ORGANIZER`, `PROCESS`) | yes | Kind |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 201 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/public/recorder/invite-qr`

**Invite Qr**

The join QR for the invite THIS phone came through — plenary only.

A plenary room shares one code, so a phone that already joined can show it
for the next phone to scan; the room adds devices without the organizer.
Deliberately absent in the other modes: their invites are per table, and a
phone re-publishing its table's code is not an asked-for flow. Exposing
the token to this session reveals nothing new — the phone joined by
holding this very token in its URL.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `authorization` | header | string | no |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/public/recorder/language`

**Set Language**

The table picks its language on the consent screen of a Record-now
Session (Block 2): allowed until the first recording exists; after that
the organizer's change-language is the path (it re-transcribes).

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `authorization` | header | string | no |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `language` | string (`en`, `it`, `de`, `fr`, `es`) | yes | Language |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/public/recorder/live-source`

**Promote Live Source**

This phone takes over its table's live captions. Its recording must be
in progress; the previous holder keeps recording and only its caption
session ends.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `authorization` | header | string | no |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `recording_id` | string | yes | Recording Id |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/public/recorder/logs`

**Ship Logs**

Offline-tolerant client log shipping — the recorder's diagnostic trail
for devices nobody can attach devtools to.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `authorization` | header | string | no |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `entries` | array of LogEntry | yes | Entries |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/public/recorder/messages/seen`

**Message Seen**

The phone has shown the organizer's message: its receipt, read by the
Live tab as "delivered 9/10". Separate from the heartbeat so the recorder
engine, which owns the heartbeat, stays untouched.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `authorization` | header | string | no |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `message_id` | integer | yes | Message Id |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/public/recorder/messages/{message_id}/feedback`

**Message Feedback**

👍 / 👎 under an AI facilitator banner on the table's phone. Only AI
messages take feedback; anything else is 404.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `message_id` | path | integer | yes |  |
| `authorization` | header | string | no |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `helpful` | boolean | yes | Helpful |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/public/recorder/participants`

**Register Participant**

One person registers at this table on the shared phone: name, the
notice they read (by hash), what they consent to. Stored as given — a
refusal is a record too — and the answer says whether the table may
record now under the assembly's rule.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `authorization` | header | string | no |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Name |
| `email` | string | no | Email |
| `notice_hash` | string | yes | Notice Hash |
| `notice_read` | boolean | no | Notice Read |
| `recording_consent` | boolean | no | Recording Consent |
| `transcription_consent` | boolean | no | Transcription Consent |
| `analysis_consent` | boolean | no | Analysis Consent |
| `publication_consent` | boolean | no | Publication Consent |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 201 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/public/recorder/participants/search`

**Search Participants**

The door's "find your name": people who registered ahead and have no
table yet. Two characters at least; names only.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `q` | query | string | yes |  |
| `authorization` | header | string | no |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/public/recorder/participants/{participant_id}/consent`

**Change Consent**

Changed their mind (after a refusal) or withdraws consent, on the
table's phone — only for a person seated at THIS table. Append-only: the
register keeps every act and the newest counts.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `participant_id` | path | string | yes |  |
| `authorization` | header | string | no |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `notice_hash` | string | yes | Notice Hash |
| `notice_read` | boolean | no | Notice Read |
| `recording_consent` | boolean | no | Recording Consent |
| `transcription_consent` | boolean | no | Transcription Consent |
| `analysis_consent` | boolean | no | Analysis Consent |
| `publication_consent` | boolean | no | Publication Consent |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 201 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/public/recorder/participants/{participant_id}/moved`

**Participant Moved**

Marked as moved to another table — the room's procedure for a refusal
(a table that is not recorded). Leaves this table's roster; consent acts
stay as they are.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `participant_id` | path | string | yes |  |
| `authorization` | header | string | no |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/public/recorder/participants/{participant_id}/seat`

**Seat Participant**

A pre-registered person sits down at this table.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `participant_id` | path | string | yes |  |
| `authorization` | header | string | no |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/public/recorder/poll-qr`

**Poll Qr**

The Polis voting link as a QR, for the people at the table to scan
with their own phones. Public link, so nothing to protect here; absent
until the organizer publishes the poll.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `authorization` | header | string | no |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/public/recorder/recordings/{recording_id}`

**Recording Status**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `recording_id` | path | string | yes |  |
| `authorization` | header | string | no |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/public/recorder/recordings/{recording_id}/chunks/{sequence_number}`

**Upload Chunk**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `recording_id` | path | string | yes |  |
| `sequence_number` | path | integer | yes |  |
| `authorization` | header | string | no |  |
| `x-chunk-sha256` | header | string | no |  |
| `x-chunk-segment` | header | integer | no |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/public/recorder/recordings/{recording_id}/chunks/{sequence_number}/finalize`

**Finalize Uploaded Chunk**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `recording_id` | path | string | yes |  |
| `sequence_number` | path | integer | yes |  |
| `x-chunk-segment` | header | integer | no |  |
| `authorization` | header | string | no |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/public/recorder/recordings/{recording_id}/chunks/{sequence_number}/parts`

**Uploaded Parts**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `recording_id` | path | string | yes |  |
| `sequence_number` | path | integer | yes |  |
| `authorization` | header | string | no |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/public/recorder/recordings/{recording_id}/chunks/{sequence_number}/parts/{part_number}`

**Upload Part**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `recording_id` | path | string | yes |  |
| `sequence_number` | path | integer | yes |  |
| `part_number` | path | integer | yes |  |
| `authorization` | header | string | no |  |
| `x-chunk-sha256` | header | string | no |  |
| `x-part-sha256` | header | string | no |  |
| `x-total-bytes` | header | integer | no |  |
| `x-chunk-segment` | header | integer | no |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/public/recorder/recordings/{recording_id}/complete`

**Complete**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `recording_id` | path | string | yes |  |
| `authorization` | header | string | no |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `total_chunks` | integer | yes | Total Chunks |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/public/recorder/recordings/{recording_id}/live`

**Live Transcript**

Provisional live captions for this table's recording (may be empty or
unavailable — that is never an error).

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `recording_id` | path | string | yes |  |
| `authorization` | header | string | no |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/public/recorder/report`

**Published Report**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `authorization` | header | string | no |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/public/recorder/report.pdf`

**Published Report Pdf**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `authorization` | header | string | no |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/public/recorder/sessions`

**Record Another Session**

Record another session from the phone's done screen (R13): a new
one-table Session like this one, and the link that joins its table.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `authorization` | header | string | no |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `round_id` | string | yes | Round Id |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 201 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/public/recorder/start`

**Start**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `authorization` | header | string | no |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `round_id` | string | yes | Round Id |
| `mime_type` | string | yes | Mime Type |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 201 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/public/recorder/status`

**Status**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `authorization` | header | string | no |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/public/register`

**Register Self**

One person registers at the code's table from their own phone: the
same record as on the shared phone (method SELF_PHONE), plus a bearer for
their page. The notice is read outside the transaction's hot path (an
in-memory snapshot) and must match what they read.

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Name |
| `email` | string | no | Email |
| `notice_hash` | string | yes | Notice Hash |
| `notice_read` | boolean | no | Notice Read |
| `recording_consent` | boolean | no | Recording Consent |
| `transcription_consent` | boolean | no | Transcription Consent |
| `analysis_consent` | boolean | no | Analysis Consent |
| `publication_consent` | boolean | no | Publication Consent |
| `token` | string | yes | Token |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 201 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/public/register/notice`

**Register Notice**

What a registration code is for — the event, the table, the notice —
before anyone types a name. Consumes nothing.

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `token` | string | yes | Token |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |
