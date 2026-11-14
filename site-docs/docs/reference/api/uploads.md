# Uploads

Resumable uploads in parts, used by session import and by attaching audio or a transcript. Organizer routes.

4 operations. Generated; do not edit.

### `POST` `/api/v1/uploads`

**Begin Upload**

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `kind` | string (`session_export`, `transcript`, `audio`) | yes | Kind |
| `filename` | string | no | Filename |
| `size_bytes` | integer | yes | Size Bytes |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 201 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `DELETE` `/api/v1/uploads/{upload_id}`

**Discard Upload**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `upload_id` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 204 | Successful Response | - |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/uploads/{upload_id}/complete`

**Complete Upload**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `upload_id` | path | string | yes |  |

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `sha256` | string | yes | Sha256 |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/uploads/{upload_id}/parts/{index}`

**Upload Part**

Raw bytes, one part of PART_BYTES at most.

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `upload_id` | path | string | yes |  |
| `index` | path | integer | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |
