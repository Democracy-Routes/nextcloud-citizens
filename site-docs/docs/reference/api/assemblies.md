# Assemblies

Assemblies, their settings, participants, tables, consent, files, report, seeds and everything else scoped to one assembly. Organizer routes.

56 operations. Generated; do not edit.

### `GET` `/api/v1/assemblies`

**List Assemblies**

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: array of AssemblyOut |

### `POST` `/api/v1/assemblies`

**Create Assembly**

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Name |
| `description` | string | no | Description |
| `language` | string (`en`, `it`, `de`, `fr`, `es`) | no | Language |
| `scheduled_at` | string (date-time) or null | no | Scheduled At |
| `recording_mode` | string (`orchestrated`, `independent`, `plenary`) | no | Recording Mode |
| `expected_participants` | integer | no | Expected Participants |
| `default_table_count` | integer | no | Default Table Count |
| `analysis_instructions` | string | no | Analysis Instructions |
| `auto_purge_device_audio` | boolean | no | Auto Purge Device Audio |
| `redact_names` | string | no | Redact Names |
| `participant_consent` | string (`required`, `optional`) | no | Participant Consent |
| `ai_facilitator` | string (`off`, `light`, `normal`, `active`) or null | no | Ai Facilitator |
| `audio_retention_days` | integer or null | no | Audio Retention Days |
| `zero_retention` | boolean | no | Zero Retention |
| `rounds` | array of RoundIn | no | Rounds |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 201 | Successful Response | `application/json`: AssemblyCreated |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/assemblies/import`

**Import Session**

A session export becomes a new, closed assembly of this organizer.
Findings and the report are not copied: the tables are analysed again
here, when a provider is configured.

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `upload_id` | string | yes | Upload Id |
| `name` | string or null | no | Name |
| `merge_tables` | array of MergeIn | no | Merge Tables |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 201 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `DELETE` `/api/v1/assemblies/{assembly_id}`

**Delete Assembly**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 204 | Successful Response | - |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/assemblies/{assembly_id}`

**Get Assembly**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: AssemblyDetail |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `PUT` `/api/v1/assemblies/{assembly_id}`

**Update Assembly**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string or null | no | Name |
| `description` | string or null | no | Description |
| `language` | string (`en`, `it`, `de`, `fr`, `es`) or null | no | Language |
| `scheduled_at` | string (date-time) or null | no | Scheduled At |
| `recording_mode` | string (`orchestrated`, `independent`, `plenary`) or null | no | Recording Mode |
| `expected_participants` | integer or null | no | Expected Participants |
| `default_table_count` | integer or null | no | Default Table Count |
| `analysis_instructions` | string or null | no | Analysis Instructions |
| `auto_purge_device_audio` | boolean or null | no | Auto Purge Device Audio |
| `redact_names` | string or null | no | Redact Names |
| `audio_retention_days` | integer or null | no | Audio Retention Days |
| `participant_consent` | string (`required`, `optional`) or null | no | Participant Consent |
| `language_auto` | boolean or null | no | Language Auto |
| `zero_retention` | boolean or null | no | Zero Retention |
| `ai_facilitator` | string (`default`, `off`, `light`, `normal`, `active`) or null | no | Ai Facilitator |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: AssemblyDetail |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `DELETE` `/api/v1/assemblies/{assembly_id}/audio`

**Delete All Audio**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/assemblies/{assembly_id}/audio.zip`

**Download All Audio**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `DELETE` `/api/v1/assemblies/{assembly_id}/close`

**Reopen Session**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 204 | Successful Response | - |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/assemblies/{assembly_id}/close`

**Close Session**

Finish the assembly: no more recordings, and the report becomes final
(frozen, so reopening cannot change what participants already read).

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/assemblies/{assembly_id}/consent-register.csv`

**Consent Register Csv**

The consent register as an auditor asks for it: one row per person
with what they accepted, against which notice, when, by which method.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/assemblies/{assembly_id}/consent-register.pdf`

**Consent Register Pdf**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/assemblies/{assembly_id}/device-report`

**Device Report**

What each phone's own log says about how it behaved (R17): browser,
wake lock, chunks captured while hidden, gaps, watchdog events — the
host script scripts/device-report.py, as the Files tab reads it.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |
| `format` | query | string | no |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/assemblies/{assembly_id}/event-kit.pdf`

**Event Kit Pdf**

The printable event kit: one card per table (number, colour band, QR),
the programme of sessions, and the recording notice in the assembly's
language. Printed the evening before; see services/event_kit.py.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/assemblies/{assembly_id}/export.zip`

**Download Session Export**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/assemblies/{assembly_id}/files`

**List Files**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/assemblies/{assembly_id}/invites`

**List Invites**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: array of InviteOut |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/assemblies/{assembly_id}/invites/generate`

**Generate Invites**

Returns fresh invite URLs + QR SVGs.
Any previously active invites for this assembly are revoked.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 201 | Successful Response | `application/json`: array of InviteGenerated |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/assemblies/{assembly_id}/invites/links`

**Invite Links**

Re-materialized QR sheet for the active invites (tokens are stored
encrypted with the app secret; invites from before that existed are
omitted and need a regenerate).

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: array of InviteGenerated |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/assemblies/{assembly_id}/invites/revoke`

**Revoke Invites**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 204 | Successful Response | - |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/assemblies/{assembly_id}/invites/sheet.pdf`

**Invite Sheet Pdf**

The printable QR sheet: four tables per A4 page, with cut lines.

Built here rather than with the browser's print, which silently dropped
every page after the first.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/assemblies/{assembly_id}/language`

**Change Language**

Change the language once recording has begun: transcripts are made
again in it (PUT refuses the field then, deliberately — this is the
explicit path, with its cost stated).

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `language` | string (`en`, `it`, `de`, `fr`, `es`) | yes | Language |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/assemblies/{assembly_id}/participants`

**List Participants**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: array of ParticipantOut |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/assemblies/{assembly_id}/participants`

**Add Participants**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `participants` | array of ParticipantIn | yes | Participants |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 201 | Successful Response | `application/json`: array of ParticipantOut |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/assemblies/{assembly_id}/participants/import-csv`

**Import Participants Csv**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `csv` | string | yes | Csv |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 201 | Successful Response | `application/json`: array of ParticipantOut |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/assemblies/{assembly_id}/participants/{participant_id}/consent`

**Organizer Records Consent Change**

Changed their mind / Withdraws consent, recorded by the organizer on
the person's word (no notice hash: the organizer vouches for it).

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |
| `participant_id` | path | string | yes |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `recording_consent` | boolean | no | Recording Consent |
| `transcription_consent` | boolean | no | Transcription Consent |
| `analysis_consent` | boolean | no | Analysis Consent |
| `publication_consent` | boolean | no | Publication Consent |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 201 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/assemblies/{assembly_id}/participants/{participant_id}/moved`

**Organizer Marks Moved**

Moved to another table: leaves the current table's roster for the
sessions still to come; seated again by name where they sit now.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |
| `participant_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/assemblies/{assembly_id}/progress`

**Assembly Progress**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/assemblies/{assembly_id}/purge-device-audio`

**Purge Device Audio**

Ask the table phones to delete their local copies of this assembly.

Every recording is written to the phone's own storage before it is
uploaded, so at the end of an event each phone still holds its table's
audio. With organisation-owned phones that is merely untidy; when citizens
use their own, it means people walk home carrying a recording of the
discussion without knowing it.

The server cannot push to a phone, so this sets a flag that travels on the
status poll each recorder already makes every few seconds. Consequences
worth being clear about:

  * It reaches phones whose recorder is still open. One closed and carried
    out of the building never receives it — though it will act on it if
    reopened while its session is still valid. The response reports how
    many phones are known to still hold audio so the UI can say what was
    covered rather than claim completion.
  * Each phone removes only recordings the SERVER has confirmed it holds,
    so this can never destroy the last copy of anything.

Only once the session is closed: before that the phones are still
recording, and their local copy is the safety net the whole design rests
on.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/assemblies/{assembly_id}/registration-link`

**Get Registration Link**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/assemblies/{assembly_id}/registration-link`

**Registration Link**

The assembly's pre-registration link (made on first ask, then the same
one): people register and consent at home, and are seated at the door
by name on the table's phone.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/assemblies/{assembly_id}/report`

**Assembly Report**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |
| `include_drafts` | query | boolean | no |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/assemblies/{assembly_id}/report.md`

**Assembly Report Markdown**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |
| `include_drafts` | query | boolean | no |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/assemblies/{assembly_id}/report.pdf`

**Assembly Report Pdf**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |
| `include_drafts` | query | boolean | no |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `DELETE` `/api/v1/assemblies/{assembly_id}/report/publish`

**Unpublish Report**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 204 | Successful Response | - |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/assemblies/{assembly_id}/report/publish`

**Publish Report**

Make the report (approved findings + AI summaries) visible on the
table recorder phones. AI drafts stay organizer-only either way.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/assemblies/{assembly_id}/report/refresh`

**Refresh Final Report**

Re-freeze the published version from the current content.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/assemblies/{assembly_id}/rounds`

**Add Round**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `title` | string | no | Title |
| `question` | string | no | Question |
| `objective` | string or null | no | Objective |
| `duration_minutes` | integer | no | Duration Minutes |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 201 | Successful Response | `application/json`: RoundOut |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/assemblies/{assembly_id}/seeds`

**List Seeds**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/assemblies/{assembly_id}/seeds`

**Create Seed**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `text` | string | yes | Text |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 201 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/assemblies/{assembly_id}/seeds/approve-all`

**Approve All Seeds**

Every draft becomes approved in one go — the plenary case, where the
statements must reach Polis minutes after the last table ends. Rejected
and exported statements are left as they are.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/assemblies/{assembly_id}/seeds/export.csv`

**Export Csv**

Approved statements, one per row, for the Polis seed box or import.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/assemblies/{assembly_id}/seeds/export.json`

**Export Json**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/assemblies/{assembly_id}/seeds/generate`

**Generate Seeds**

Queue the model run. Untouched drafts are replaced; reviewed, edited
and hand-written statements stay. `target` is how many statements in
all; the listing's recommendation when not given.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Request body** (`application/json`, optional)

| Field | Type | Required | Description |
|---|---|---|---|
| `target` | integer or null | no | Target |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 202 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `PUT` `/api/v1/assemblies/{assembly_id}/seeds/order`

**Reorder Seeds**

`ids` in the wanted order; statements not named keep their relative
order after them.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `ids` | array of string | yes | Ids |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/assemblies/{assembly_id}/seeds/poll-qr`

**Poll Qr**

The voting link as a QR for the organizer's QR tab, once sent.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `DELETE` `/api/v1/assemblies/{assembly_id}/seeds/poll/publish`

**Unpublish Poll**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 204 | Successful Response | - |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/assemblies/{assembly_id}/seeds/poll/publish`

**Publish Poll**

Put the Polis voting link on the table phones (and the participants'
own pages): the recorder shows it with a QR code, like the report.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/assemblies/{assembly_id}/seeds/push`

**Push Seeds**

Queue the send to the configured Polis instance; the job does the
network work. Same gate as the export: the review must be finished.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 202 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `DELETE` `/api/v1/assemblies/{assembly_id}/seeds/{seed_id}`

**Delete Seed**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |
| `seed_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 204 | Successful Response | - |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `PUT` `/api/v1/assemblies/{assembly_id}/seeds/{seed_id}`

**Update Seed**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |
| `seed_id` | path | string | yes |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `text` | string or null | no | Text |
| `status` | string (`DRAFT`, `APPROVED`, `REJECTED`) or null | no | Status |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/assemblies/{assembly_id}/synthesis`

**Generate Synthesis**

How the discussion developed across sessions: queue the synthesis
(at least two sessions with a summary). Happens by itself at closing;
this is for an organizer who wants it earlier or again.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 202 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/assemblies/{assembly_id}/tables`

**Add Table**

Add the next table — to every round at once — while the event runs.

The QR code for the new table is in this response only; the codes already
on the wall stay valid.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 201 | Successful Response | `application/json`: TableAdded |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/assemblies/{assembly_id}/tables/{table_number}/device-logs`

**Device Logs**

Tail of the latest device's shipped client log for one table.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |
| `table_number` | path | integer | yes |  |
| `tail` | query | integer | no |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/assemblies/{assembly_id}/tables/{table_number}/facilitation`

**Set Table Facilitation**

The Live tab's "Pause AI" for one table — or a level of its own;
"default" follows the assembly again.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |
| `table_number` | path | integer | yes |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `level` | string (`default`, `off`, `light`, `normal`, `active`) | yes | Level |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `DELETE` `/api/v1/assemblies/{assembly_id}/transcripts`

**Delete All Transcripts**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `assembly_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |
