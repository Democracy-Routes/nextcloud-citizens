# Other

Health, findings, participants, help requests and the static entry points.

9 operations. Generated; do not edit.

### `PUT` `/api/v1/findings/{finding_id}`

**Update Finding**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `finding_id` | path | string | yes |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `status` | string or null | no | Status |
| `title` | string or null | no | Title |
| `summary` | string or null | no | Summary |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/health`

**Health**

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: object |

### `POST` `/api/v1/help-requests/{request_id}/acknowledge`

**Acknowledge Help**

The organizer has seen a table's hand. The table's phone reads this
on its next status poll; the row leaves the Live tab's attention list.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `request_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `DELETE` `/api/v1/participants/{participant_id}`

**Delete Participant**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `participant_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 204 | Successful Response | - |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/css/citizens-main.css`

**Organizer Style Stub**

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |

### `GET` `/js/citizens-main.js`

**Organizer Loader**

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |

### `GET` `/recorder`

**Recorder Redirect**

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |

### `GET` `/recorder.html`

**Recorder Page**

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |

### `GET` `/recorder/`

**Recorder Redirect Slash**

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
