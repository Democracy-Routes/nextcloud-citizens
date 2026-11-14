# Sessions

Create and list Sessions (including Record now). Organizer routes.

5 operations. Generated; do not edit.

### `GET` `/api/v1/sessions`

**List Sessions**

Every Session the user owns — standalone ones and those inside assemblies —
in product vocabulary (domain/vocabulary.py).

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: array of SessionOut |

### `POST` `/api/v1/sessions`

**Create Session**

Start a Session: question, optional objective, tables — no assembly.

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `question` | string | no | Question |
| `objective` | string or null | no | Objective |
| `duration_minutes` | integer | no | Duration Minutes |
| `table_count` | integer | no | Table Count |
| `recording_mode` | string (`orchestrated`, `independent`, `plenary`) | no | Recording Mode |
| `language` | string (`en`, `it`, `de`, `fr`, `es`) | no | Language |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 201 | Successful Response | `application/json`: SessionCreated |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/sessions/record-now`

**Record Now**

Record now: a one-table Session and the link that makes this phone its recorder.

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `language` | string (`en`, `it`, `de`, `fr`, `es`) | no | Language |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 201 | Successful Response | `application/json`: RecordNowOut |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/sessions/{session_id}`

**Get Session**

A Session by its id — the same id every `/rounds/{id}` route accepts.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `session_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: SessionOut |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/sessions/{session_id}/promote`

**Promote Session**

A standalone Session becomes an Assembly (an event of several sessions),
keeping everything it already has. Idempotent for an assembly.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `session_id` | path | string | yes |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Name |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: PromotedOut |
| 422 | Validation Error | `application/json`: HTTPValidationError |
