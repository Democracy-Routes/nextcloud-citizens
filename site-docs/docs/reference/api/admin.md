# Administration

Settings, provider tests, Vosk models and instance status. Administrator routes.

13 operations. Generated; do not edit.

### `GET` `/api/v1/admin/about`

**About**

What the About tab of Settings shows: the running version and schema,
the transcription engine's state, storage and the job queue. Opened by
a person, never polled — so it may do a little work.

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |

### `POST` `/api/v1/admin/facilitator/tick`

**Facilitator Tick**

Run the AI facilitator's minute now (it runs by itself from the sweep):
for a rehearsal or a smoke test that cannot wait for the clock.

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |

### `DELETE` `/api/v1/admin/logo`

**Delete Logo**

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 204 | Successful Response | - |

### `GET` `/api/v1/admin/logo`

**Get Logo**

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |

### `PUT` `/api/v1/admin/logo`

**Upload Logo**

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `data` | string | yes | Data |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 204 | Successful Response | - |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/admin/ping`

**Ping**

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |

### `GET` `/api/v1/admin/providers`

**Get Providers**

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |

### `PUT` `/api/v1/admin/providers`

**Update Providers**

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `stt_provider` | string (`mistral`, `deepgram`, `whisper`, `vosk`) or null | no | Stt Provider |
| `vosk_mode` | string (`builtin`, `server`) or null | no | Vosk Mode |
| `stt_live_enabled` | boolean or null | no | Stt Live Enabled |
| `stt_batch_enabled` | boolean or null | no | Stt Batch Enabled |
| `mistral_api_key` | string or null | no | Mistral Api Key |
| `mistral_live_model` | string or null | no | Mistral Live Model |
| `mistral_batch_model` | string or null | no | Mistral Batch Model |
| `deepgram_api_key` | string or null | no | Deepgram Api Key |
| `deepgram_live_model` | string or null | no | Deepgram Live Model |
| `deepgram_batch_model` | string or null | no | Deepgram Batch Model |
| `deepgram_live_url` | string or null | no | Deepgram Live Url |
| `whisper_api_key` | string or null | no | Whisper Api Key |
| `whisper_base_url` | string or null | no | Whisper Base Url |
| `whisper_batch_model` | string or null | no | Whisper Batch Model |
| `whisper_live_model` | string or null | no | Whisper Live Model |
| `mistral_live_url` | string or null | no | Mistral Live Url |
| `vosk_url` | string or null | no | Vosk Url |
| `vosk_language_models` | string or null | no | Vosk Language Models |
| `vosk_batch_model` | string or null | no | Vosk Batch Model |
| `stt_concurrency_deepgram_live` | integer or null | no | Stt Concurrency Deepgram Live |
| `stt_concurrency_deepgram_batch` | integer or null | no | Stt Concurrency Deepgram Batch |
| `stt_concurrency_mistral_live` | integer or null | no | Stt Concurrency Mistral Live |
| `stt_concurrency_mistral_batch` | integer or null | no | Stt Concurrency Mistral Batch |
| `stt_concurrency_vosk_live` | integer or null | no | Stt Concurrency Vosk Live |
| `stt_concurrency_vosk_batch` | integer or null | no | Stt Concurrency Vosk Batch |
| `stt_concurrency_whisper_live` | integer or null | no | Stt Concurrency Whisper Live |
| `stt_concurrency_whisper_batch` | integer or null | no | Stt Concurrency Whisper Batch |
| `analysis_base_url` | string or null | no | Analysis Base Url |
| `analysis_model` | string or null | no | Analysis Model |
| `analysis_api_key` | string or null | no | Analysis Api Key |
| `analysis_enabled` | boolean or null | no | Analysis Enabled |
| `analysis_extra_instructions` | string or null | no | Analysis Extra Instructions |
| `facilitator_level` | string (`off`, `light`, `normal`, `active`) or null | no | Facilitator Level |
| `facilitator_base_url` | string or null | no | Facilitator Base Url |
| `facilitator_model` | string or null | no | Facilitator Model |
| `facilitator_api_key` | string or null | no | Facilitator Api Key |
| `facilitator_interval_minutes` | integer or null | no | Facilitator Interval Minutes |
| `facilitator_dominance_percent` | integer or null | no | Facilitator Dominance Percent |
| `facilitator_silence_seconds` | integer or null | no | Facilitator Silence Seconds |
| `organization_name` | string or null | no | Organization Name |
| `audio_retention_days` | integer or null | no | Audio Retention Days |
| `record_now_idle_close_minutes` | integer or null | no | Record Now Idle Close Minutes |
| `consent_controller` | string or null | no | Consent Controller |
| `consent_contact` | string or null | no | Consent Contact |
| `org_address` | string or null | no | Org Address |
| `org_dpo` | string or null | no | Org Dpo |
| `org_hosting` | string or null | no | Org Hosting |
| `org_authority` | string or null | no | Org Authority |
| `polis_url` | string or null | no | Polis Url |
| `polis_api_key` | string or null | no | Polis Api Key |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/admin/providers/test`

**Test Provider**

**Request body** (`application/json`, required)

| Field | Type | Required | Description |
|---|---|---|---|
| `target` | string (`mistral`, `deepgram`, `whisper`, `vosk`, `analysis`, `facilitator`, `polis`) | yes | Target |
| `api_key` | string or null | no | Api Key |
| `base_url` | string or null | no | Base Url |
| `model` | string or null | no | Model |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `GET` `/api/v1/admin/vosk/models`

**Vosk Models Overview**

Installed and available speech models for the built-in engine, with
install progress and the engine's state (services/vosk_models.py).

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |

### `DELETE` `/api/v1/admin/vosk/models/{name}`

**Vosk Model Remove**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `name` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/admin/vosk/models/{name}/cancel`

**Vosk Model Cancel**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `name` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |

### `POST` `/api/v1/admin/vosk/models/{name}/install`

**Vosk Model Install**

**Parameters**

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `name` | path | string | yes |  |

**Responses**

| Code | Meaning | Body |
|---|---|---|
| 202 | Successful Response | `application/json`: any |
| 422 | Validation Error | `application/json`: HTTPValidationError |
