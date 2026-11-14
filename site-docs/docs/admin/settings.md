# Settings reference

Open **Citizens, Settings** (Nextcloud administrators only; in standalone mode, administrator
accounts). Settings has four tabs: **Transcription**, **AI**, **Organisation** and **About**, each a
column of cards, one concern per card.

**Every card has its own Save button**, enabled only when something in that card changed, and it
saves only that card: changing the retention never commits a half-typed API key on another tab. The
Vosk model table and the logo apply immediately and have no Save. API keys are never shown again
after saving; the interface sees only that a key is configured and its last four characters. Use the
*Test* buttons before saving: they check what you typed. A key you saved cannot be sent to an
arbitrary host, because testing an endpoint you typed requires a key you typed.

In Nextcloud mode the values are kept in Nextcloud's app configuration (API keys marked *sensitive*);
in standalone mode they are kept in an app database table.

## Transcription

Choose an engine. Only the selected engine's card is shown.

| Engine | Runs | Speaker labels | Live captions |
|---|---|---|---|
| Deepgram | hosted | yes | native streaming, with speakers |
| Mistral (Voxtral) | hosted | on final transcripts | Voxtral Realtime, no speakers while live |
| Whisper (OpenAI-compatible) | hosted **or your own server** | only on diarizing servers | rolling 20-second windows; a line may be revised |
| Vosk | **your own server, or built into the app**, offline | no | native streaming, no punctuation |

Any endpoint speaking the OpenAI audio API works for Whisper (OpenAI itself, Speaches, whisper.cpp,
LocalAI, vLLM, WhisperX). Deepgram's caption endpoint is configurable too, so a self-hosted server
speaking the same streaming protocol, such as WhisperLiveKit, can drive captions without leaving your
network. A Whisper server that adds diarization (WhisperX-based, or OpenAI's
`gpt-4o-transcribe-diarize` model) keeps speaker labels; plain Whisper and Vosk produce transcripts
without them, and reports then omit the "who said it" attribution while keeping every quote and
finding.

### Live captions and the final transcript { #live-captions-and-the-final-transcript }

Two checkboxes decide what is produced, and they work independently.

| Live | Final | What happens |
|---|---|---|
| on | on | Tables see captions while they talk; each recording is transcribed again afterwards from the complete audio. **The final transcript is the record** and the one the analysis reads. |
| off | on | No captions during the round. Each recording is transcribed once it is uploaded, and that is the record. |
| on | off | **The captions are the record.** Nothing is transcribed a second time. |
| off | off | Nothing is transcribed at all: audio is stored and there is no transcript, no analysis and an empty report. Settings warns about this. |

!!! tip "Live-only is a deliberate choice"
    Transcribing the finished audio a second time costs roughly ten minutes of processing per
    half-hour table, for text a self-hosted engine already worked out while listening. Skipping it
    matters most on a small server running Vosk for ten tables at once.

What you give up is accuracy and completeness. Captions are produced under time pressure: audio is
dropped if the engine falls behind (logged when it happens), and a session that fails resumes after a
cooldown, so speech in that window is never captioned. A report built from captions says so in its
methodology note in every format. Nothing is stuck: **Re-transcribe** on any table's row in the Files
tab transcribes the stored audio properly and re-runs the analysis, even with Final transcription
switched off.

### Vosk: two ways to run it

Vosk needs **a separate model per language**, but one engine can hold several: each recording names the
model it wants, and the language you set on an assembly chooses it. Settings, Transcription, *Vosk
engine* has an **Engine** choice.

=== "Built-in engine"

    The engine runs inside the app container, on a loopback socket nobody else can reach, and loads
    models that you install from Settings into `models/` under the data volume. Nothing to deploy,
    nothing leaves the server.

    The card shows whether the engine is running, how much memory is free for models in this
    container, and a table of models per language, each **small** or **large**:

    | | Size on disk | Good for |
    |---|---|---|
    | small | about 40-50 MB | fast; fine for live captions and modest rooms |
    | large | about 1.2-1.9 GB | noticeably better transcripts; needs the memory (below) |

    Press **Install** next to a model. It downloads from `alphacephei.com` (the only thing the engine
    ever fetches; no audio goes there) with progress, then unpacks. The install is atomic: the model is
    moved into place in one step only when complete, so a crash, a restart or **Cancel** leaves nothing
    half-installed. **Remove** deletes a model and is refused while a live session is using it. Then
    fill the per-language table with the model names.

    **Memory.** A loaded model takes about 1.3 times its size on disk. The engine refuses to load a
    model that does not fit the container's free memory and says so ("needs about N MB") rather than
    taking the app down. Two languages stay loaded at once; a model idle for 30 minutes is unloaded, and
    one in use never is.

    * Scripts install: `CITIZENS_VOSK_BUILTIN=1` raises the container's memory from 2g to 3500m and
      stops the separate `citizens-vosk` container. `CITIZENS_MEMORY` overrides the figure, e.g.
      `CITIZENS_VOSK_BUILTIN=1 CITIZENS_MEMORY=6g scripts/event-up.sh`.
    * AppAPI-managed install: the deploy daemon's memory setting applies.
    * Standalone: set `mem_limit` and `memswap_limit` in `docker-compose.standalone.yml` (6g for
      large models).

=== "Vosk server at a URL"

    A Vosk server you run elsewhere, or on this host with `scripts/vosk-up.sh`, which downloads nothing:

    ```sh
    scripts/vosk-model.sh --list                       # what is installed
    scripts/vosk-model.sh vosk-model-small-de-0.15     # add German
    scripts/vosk-down.sh                               # stop (--purge deletes models)
    ```

    Set the server URL and, in *Model per language*, the **model name** for each language:

    ```text
    Server URL   ws://citizens-vosk:2700

                 Live captions                  Final transcript
    Italiano     vosk-model-small-it-0.22       vosk-model-small-it-0.22
    English      vosk-model-small-en-us-0.15    vosk-model-small-en-us-0.15
    ```

    A blank final model reuses the live one, and a language with no row uses whatever model the server
    started with. The server must be reachable **from the app container**, so use the container name
    rather than `localhost`. Vosk has no authentication: never publish its port beyond `127.0.0.1`.
    Models load on first use and are freed when idle (30 minutes by default,
    `VOSK_MODEL_IDLE_SECONDS`), two at a time (`VOSK_MODEL_CACHE`). The script runs a lightly patched
    `asr_server.py` in `scripts/vosk/` that chooses the model per connection, caches loads and frees
    idle models.

Switching the engine back to a server stops the built-in one; the installed models stay in `models/` so
you can switch again.

## AI

### Analysis

Any OpenAI-compatible endpoint works: Mistral, OpenAI, or a self-hosted server such as Ollama or vLLM.
Set the base URL, model and key. Choosing a self-hosted endpoint keeps transcripts on your own
infrastructure. *Test* sends one real completion to the configured model.

**Additional analysis instructions** apply to every assembly on the instance; each assembly can add its
own on top (topic context, glossary). They are appended to the built-in prompts; the JSON output
contract and the evidence rules stay protected.

Two limits keep one table's analysis affordable: a finding cites at most six quotations, and a table
transcript longer than roughly 180,000 characters is cut for the analysis prompt (the start is kept, the
rest is noted as cut, and the log says how much was left out).

### AI facilitator { #ai-facilitator }

Off unless somebody turns it on. Settings, AI, *AI facilitator* sets:

* the instance default level (Off, Light, Normal, Active; at most 2, 4 or 8 nudges per table per
  session);
* an optional model of its own (base URL, model, API key; blank fields fall back to the analysis
  model's);
* the thresholds behind its nudges: minutes between two nudges at a table, the speaking share that
  counts as one voice dominating, and the seconds of silence before an open question.

*Test* makes one real completion with the facilitator's settings. Each assembly chooses its own level on
the Overview tab ("Default from Settings" follows this page), each table can switch it off from its
phone's tech sheet, and the Live tab can *Pause AI* per table. Once a minute, for every table of a
running session whose level is not Off, the server reads the table's live captions (names replaced by
pseudonyms), the time left and, when the engine labels speakers, the anonymous speaking balance, and
only when a trigger fires asks the model for one short sentence or nothing. The advice reaches the
facilitator's phone first and the table's phones directly only when no facilitator phone is connected.
Every nudge, its delivery and the thumbs counts are in the Live tab's *AI facilitator* log and in the
audit trail. `POST /api/v1/admin/facilitator/tick` runs the minute by hand for a rehearsal. Nothing is
called without a key; a failing model is logged and skipped.

### Polis { #polis }

**Settings, AI, Polis** holds the URL of a Polis instance and an API key issued by its operator (the
Citizens-Polis fork; `deploy/prod/create-apikey.sh <email>` there). With both set, organizers get
**Send to Polis** in Results, Polis seeds. **Test connection** calls the instance and answers whose key
it is. The key is stored like the other API keys and never shown again. Only statement text is sent. See
[Polis consultation](../organizers/polis.md), [Connecting an installation](../bridge/setup.md) (key, test, rotation, troubleshooting) and the [bridge contract](../bridge/contract.md).

## Organisation

* **Organisation name and logo** appear on the PDF reports. The logo applies immediately.
* **Data controller and contact** for the consent notice: controller (empty falls back to the
  organisation name), contact, postal address, data-protection contact, hosting, supervisory authority
  (empty: a default by language). Blank fields are left out of the notice, never shown as placeholders.
  See [Consent and the notice](../privacy/consent.md).
* **Retention** sets how many days after an assembly is closed its audio is deleted; `0` keeps it
  indefinitely. Each assembly can override it, and *Zero retention* is a per-assembly choice. See
  [After the assembly](../organizers/after.md#retention).
* **Users** (standalone mode only): invite organizers by mail or with a link copied from the log,
  resend links, change roles, disable and delete accounts. See
  [Run standalone](../getting-started/standalone.md).

## About

Shows the running version, the database schema revision, the transcription engine's state, disk space,
the job queue and the time of the last housekeeping pass. These are the first things to read into a
support request.

## Settings keys

The keys behind the cards, with their defaults. The defaults are the ones in
`citizens/services/provider_config.py`.

| Key | Default | Meaning |
|---|---|---|
| `stt_provider` | `mistral` | Selected engine: `mistral`, `deepgram`, `whisper` or `vosk` |
| `stt_live_enabled` | `1` | Live captions on |
| `stt_batch_enabled` | `1` | Final transcription on |
| `deepgram_live_model` / `deepgram_batch_model` | `nova-3` | Deepgram models |
| `deepgram_live_url` | `wss://api.deepgram.com/v1/listen` | Caption endpoint; any server speaking the protocol works |
| `mistral_live_model` | `voxtral-mini-transcribe-realtime-2602` | Mistral live model |
| `mistral_live_url` | `wss://api.mistral.ai/v1/audio/transcriptions/realtime` | Mistral live endpoint |
| `mistral_batch_model` | `voxtral-mini-latest` | Mistral final model |
| `whisper_base_url` | `https://api.openai.com/v1` | Any OpenAI-compatible audio endpoint |
| `whisper_batch_model` | `whisper-1` | Whisper final model |
| `whisper_live_model` | empty | Faster model for rolling captions; empty uses the batch model |
| `vosk_url` | `ws://localhost:2700` | Vosk server |
| `vosk_mode` | `server` | `server`, or `builtin` for the in-container engine |
| `vosk_language_models` | empty | JSON map of language code to model |
| `stt_concurrency_<provider>_live` and `_batch` | see below | Server-wide caps on concurrent transcription work |
| `analysis_base_url` | `https://api.mistral.ai/v1` | Analysis endpoint |
| `analysis_model` | `mistral-large-latest` | Analysis model |
| `analysis_enabled` | `1` | Analysis on |
| `analysis_extra_instructions` | empty | Appended to the built-in prompts |
| `facilitator_level` | `off` | Instance default AI facilitator level |
| `facilitator_base_url`, `facilitator_model` | empty | The facilitator's own model; blank uses the analysis model |
| `facilitator_interval_minutes` | `4` | Minutes between nudges at a table |
| `facilitator_dominance_percent` | `60` | Speaking share that counts as one voice dominating |
| `facilitator_silence_seconds` | `90` | Silence before an open question |
| `polis_url` | empty | Polis instance |
| `organization_name`, `consent_controller`, `consent_contact`, `org_address`, `org_dpo`, `org_hosting`, `org_authority` | empty | Organisation and consent-notice data |
| `audio_retention_days` | `0` | Days after closing before audio is deleted; `0` keeps it |

Secret keys, stored as sensitive and never returned by any API: `mistral_api_key`, `deepgram_api_key`,
`whisper_api_key`, `analysis_api_key`, `facilitator_api_key`, `polis_api_key`.

Default concurrency caps (live / batch): Deepgram 10 / 5, Mistral 15 / 5, Vosk 5 / 2, Whisper 2 / 1.
Over-cap phones keep recording and their captions wait for a slot.

## Languages

Both halves of the app follow a language: the table phones and participant pages follow the assembly's
language (or the language detected on a Record-now session), and the organizer interface follows the
user's own language setting. Translation catalogues live in `frontend/src/i18n/` and
`frontend/src/i18n/organizer/`; a translator can edit them without touching code, and the build fails on
a key missing in one language. See [Frontend](../architecture/frontend.md).
