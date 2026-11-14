# Providers and what leaves the server

**Nothing leaves the server until an administrator configures a provider.** A fresh install performs no
transcription and no analysis.

## Egress table

| Step | What is sent | Where | When |
|---|---|---|---|
| Transcription | the assembled audio of one recording | Deepgram, Mistral, or the Whisper endpoint you configure (which can be your own server) | only after an admin configures an engine, and only with **Final transcription** enabled |
| Live captions | about 10-second audio chunks during recording | whichever engine is configured; none if it is self-hosted | only if live captions are enabled |
| Analysis | transcript text (never audio) | the configured endpoint, which may be your own server | only after an admin configures it |
| Polis | the approved statements (text only), the assembly name and description | the Polis instance you configure | only when an organizer presses **Send to Polis** |
| Vosk model download | a model file request to `alphacephei.com`; no audio | the model host | only when an administrator presses **Install** for a built-in Vosk model |

With live captions only, the assembled recording is never sent anywhere: the chunks streamed during the
round are the sole egress, and with Vosk or a self-hosted Whisper server there is none at all.

Everything else (audio, transcripts, findings, reports) stays in the app's own storage on your server,
never in users' Nextcloud files.

## Choosing for privacy

| If you want... | Choose |
|---|---|
| Recordings never to leave your infrastructure | Vosk (built-in or your own server), or Whisper against your own server |
| Speaker labels | Deepgram, Mistral final transcripts, or a diarizing Whisper server |
| Transcripts never to leave your infrastructure | A self-hosted analysis endpoint (Ollama, vLLM) |
| The least processing | Live-only: captions are the record and nothing is transcribed a second time |

Plain Whisper and Vosk produce transcripts without speaker labels, and reports then omit the "who said
it" attribution while keeping every quote and finding.

## What the analysis provider sees

Only transcript text. Names listed under *Assembly details* are replaced by pseudonyms before the text
is sent; see [Pseudonyms and names](../privacy/pseudonyms.md). The audio sent for transcription still
carries names as spoken, so use a self-hosted engine if that matters.

## What participants are told

The recorder shows an information screen before recording starts. It names the transcription engine,
whether that engine is an outside service, how long audio is kept, and how speakers are labelled. The
text is generated from the server's live configuration, so it cannot drift from what the app does. The
analysis provider is named from the configured endpoint: a known hosted service by name (Mistral AI,
OpenAI, Anthropic, Google, Groq, OpenRouter), a local endpoint as the organisation's own server, any
other by its hostname. See [Consent and the notice](../privacy/consent.md).

## Trust boundary

An administrator can point transcription at any endpoint, including one that is not the provider
participants were told about. This is an administrative trust boundary, not a technical one.

## API keys

Provider API keys are stored as sensitive configuration, never returned by any API, never written to a QR
code and never logged; the interface sees only `configured: true` and the last four characters. A
redaction processor scrubs anything matching `secret|token|passw|api_key|authorization|bearer|credential|cookie`
from every log event on every sink as defence in depth. In standalone mode the keys are encrypted with
`APP_SECRET`, so a lost secret means entering them again.

!!! warning "Costs"
    Hosted providers bill by use. A full load test replays real speech at wall-clock speed and bills
    live captions plus batch transcription plus analysis for every minute. Run the smoke test first.
    See [Testing](../architecture/testing.md).
