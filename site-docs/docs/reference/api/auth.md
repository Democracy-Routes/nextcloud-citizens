# Accounts (standalone)

Sign-in, invitations and password reset in standalone mode.

7 operations. Generated; do not edit.

### `GET` `/api/v1/auth/config`

**Auth Config**

How this instance signs people in. Public: the login page needs it.

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |

### `POST` `/api/v1/auth/login`

**Login**

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `username` | string | yes | Username |
| `password` | string | yes | Password |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/auth/logout`

**Logout**

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 204 | Successful Response | - |

### `GET` `/api/v1/auth/me`

**Me**

The signed-in person. In Nextcloud mode only the id is known here.

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |

### `PUT` `/api/v1/auth/me`

**Update Me**

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `display_name` | string or null | no | Display Name |
| `language` | string (`en`, `it`, `de`, `fr`, `es`) or null | no | Language |
| `current_password` | string or null | no | Current Password |
| `password` | string or null | no | Password |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/auth/reset`

**Request Reset**

Always 202: whether the address has an account is not revealed.

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `email` | string | yes | Email |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 202 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/auth/set-password`

**Set Password**

An invitation or reset link's landing: set the password, sign in.

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `token` | string | yes | Token |
| `password` | string | yes | Password |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |
