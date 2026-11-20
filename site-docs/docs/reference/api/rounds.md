# Rounds (sessions)

A Session is a Round in the schema: these routes start and end it, monitor it, and hold its findings, analysis and messages. Organizer routes.

20 operations. Generated; do not edit.

### `DELETE` `/api/v1/rounds/{round_id}`

**Delete Round**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `round_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 204 | Successful Response | - |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `PUT` `/api/v1/rounds/{round_id}`

**Update Round**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `round_id` | path | string | yes |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `title` | string or null | no | Title |
| `question` | string or null | no | Question |
| `objective` | string or null | no | Objective |
| `duration_minutes` | integer or null | no | Duration Minutes |
| `position` | integer or null | no | Position |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: RoundOut |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/rounds/{round_id}/analysis/cancel`

**Cancel Pending Analysis**

Stop the analysis jobs that have not started: queued, or waiting out a
retry. A job already mid-request finishes within its HTTP timeout and
is reported, not interrupted.

Without this, "Analysis is already running for every table" was the
whole story for as long as the backoff lasted — eight minutes at the
2026-09-18 rehearsal, with the provider answering 429 every time.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `round_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/rounds/{round_id}/analyze`

**Request Analysis**

(Re)run analysis for every transcribed table of the round; cross-table
clustering follows automatically once all tables finish.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `round_id` | path | string | yes |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `force` | boolean | no | Force |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 202 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/rounds/{round_id}/assignments/copy-previous`

**Copy Previous**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `round_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: array of TableOut |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/rounds/{round_id}/assignments/move`

**Move**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `round_id` | path | string | yes |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `participant_id` | string | yes | Participant Id |
| `to_table_id` | string | yes | To Table Id |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: array of TableOut |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/rounds/{round_id}/assignments/randomize`

**Randomize**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `round_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: array of TableOut |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/rounds/{round_id}/assignments/remix`

**Remix**

Seat everyone for this session with a goal — meet new people, random,
or continuity — including the people who registered at the tables.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `round_id` | path | string | yes |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `goal` | string (`new_people`, `random`, `continuity`) | no | Goal |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/rounds/{round_id}/end`

**End Round**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `round_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: RoundOut |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/rounds/{round_id}/findings`

**Round Findings**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `round_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/rounds/{round_id}/findings/approve`

**Approve Drafts**

Approve every draft finding in a round, or in one of its tables.

Reviewing findings one at a time is what an organizer does after an
assembly, and they said it was tedious enough to want a way to skip review
entirely. A person pressing this button is the review the report's
methodology note records; when the server approves findings by itself (a
Record now session) the note says so instead. It is a statement about THIS
generation of findings — a later analysis run replaces the generation,
approvals included (services/analysis._delete_existing), and the
organizer confirms that before re-running.

Only DRAFT findings. A REJECTED one is a decision somebody made, and
quietly reversing it in a bulk action would be the worst kind of surprise.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `round_id` | path | string | yes |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `table_number` | integer or null | no | Table Number |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/rounds/{round_id}/interventions`

**Round Interventions**

What the AI facilitator said at each table of this session, to whom,
and what people thought of it.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `round_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/rounds/{round_id}/messages`

**List Messages**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `round_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: array of MessageOut |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/rounds/{round_id}/messages`

**Send Message**

Say something to every table of this session, or to one: "5 minutes
left", "wrap up", a prompt. Rides the phones' status poll; the phones
report receipt, which GET below shows as delivered / not yet.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `round_id` | path | string | yes |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `kind` | string (`TIME_LEFT`, `WRAP_UP`, `PROMPT`, `CUSTOM`) | yes | Kind |
| `text` | string or null | no | Text |
| `minutes` | integer or null | no | Minutes |
| `target_table_number` | integer or null | no | Target Table Number |
| `sound` | boolean | no | Sound |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 201 | Successful Response | `application/json`: MessageOut |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/rounds/{round_id}/monitor`

**Round Monitor**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `round_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/rounds/{round_id}/readiness`

**Round Readiness**

Can each table record? READY / NEEDS_ATTENTION / BLOCKED with reason
codes — the monitor's judgement without its detail, for an exception-first
view or an organizer's autopilot.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `round_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/rounds/{round_id}/recluster`

**Request Reclustering**

Run only the cross-table clustering again, from the tables' current
findings — not the ten table analyses a full re-run costs.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `round_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 202 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/rounds/{round_id}/start`

**Start Round**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `round_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: RoundOut |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/rounds/{round_id}/tables`

**Round Tables**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `round_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: array of TableOut |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/rounds/{round_id}/tables/{table_id}/recordings`

**Table Recordings**

Every recording of one table's discussion in one round — however many
phones made them — with the recorder slot each came from.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `round_id` | path | string | yes |  |
| `table_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |
