# Recordings

Operations on one recording: transcripts, audio, retranscription, handover and promotion. Organizer routes.

12 operations. Generated; do not edit.

### `POST` `/api/v1/recordings/{recording_id}/abandon-upload`

**Abandon Upload**

Stop waiting for a table whose phone never finished uploading.

A stalled upload is swept automatically after a while, but during a live
event the organizer needs to move the round on now rather than wait. The
audio already received is kept, and the table can still re-record or the
phone can still finish uploading later — UPLOAD_INCOMPLETE transitions back.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `recording_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/recordings/{recording_id}/assemble`

**Retry Assembly**

Try assembling this recording's audio again.

The only other place that ever enqueues ASSEMBLE_AUDIO is
complete_recording, which refuses a recording that is already ASSEMBLING —
so when assembly failed for good (a full disk exhausting the retries) there
was nothing an organizer could do about it. The chunks are still on disk;
once space is free this is the way back.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `recording_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 202 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `DELETE` `/api/v1/recordings/{recording_id}/audio`

**Delete Audio**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `recording_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/recordings/{recording_id}/audio`

**Download Audio**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `recording_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/recordings/{recording_id}/audio`

**Attach Audio**

A finished audio file becomes this recording's audio; transcription
runs as it would have after assembly.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `recording_id` | path | string | yes |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `upload_id` | string | yes | Upload Id |
| `mime_type` | string | no | Mime Type |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/recordings/{recording_id}/finish`

**Finish Recording**

Finish a table's recording from the Live tab.

Asks the phone first: it finishes on its next poll, so every chunk it
holds is uploaded and verified as if somebody had tapped Finish at the
table. A phone that does not answer in FINISH_REQUEST_GRACE_SECONDS is
finished server-side by the sweep with the audio already received, and
whatever it sends later goes into a continuation of the same table.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `recording_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/recordings/{recording_id}/promote-live-source`

**Promote Live Source**

Make this recording the one that feeds its table's live captions.

For a table with more than one recorder phone: the organizer picks which
one the room reads. The previous holder keeps recording; only its caption
session ends.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `recording_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/recordings/{recording_id}/replace-device`

**Replace Device**

This table's phone is gone; let another one take over.

Distinct from abandon-upload, which means "stop waiting, it may yet come
back". This means a person walked to the table and saw a dead phone, and
that confidence buys two things abandon does not do:

  * the partial recording is assembled and transcribed immediately, so most
    of the round becomes a real transcript instead of waiting for somebody
    to remember a manual Retry afterwards;
  * the table is released at once, rather than in twenty minutes, which on
    a thirty-minute round is the difference between recording the rest of
    the discussion and losing it.

The replacement phone simply rescans the SAME QR code — invites are not
single-use — and starts a second recording for this table and round.

The old phone's session is deliberately NOT revoked. If it is charged
later, its unsent chunks are all from before it died, so they belong to
this recording and overlap nothing; revoking would strand them, because
uploading them needs its bearer token.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `recording_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/recordings/{recording_id}/transcribe`

**Request Transcription**

Manual (re)transcription from the stored audio.

Runs the full batch transcription regardless of the Settings switches, so it
is also how an organizer upgrades a captions-derived transcript to a real
one. store_transcript replaces what is there and flags findings whose quotes
came from the old segments, so the transcript need not be deleted first.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `recording_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 202 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `DELETE` `/api/v1/recordings/{recording_id}/transcript`

**Delete Transcript**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `recording_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/recordings/{recording_id}/transcript`

**Get Transcript**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `recording_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/recordings/{recording_id}/transcript`

**Attach Transcript**

A transcript made elsewhere becomes this recording's; the table's
analysis runs again.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `recording_id` | path | string | yes |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `upload_id` | string | yes | Upload Id |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |
