# Vosk speaker vectors — feasibility spike (0.7, 2026-10-06)

**Question.** Can the self-hosted Vosk path give the facilitator an
anonymous, realtime speaking-balance signal (Voice A / B / C, no identity)
without breaking or requiring anything for Vosk users who do not want it?

**Answer.** Yes, cleanly. The server we already deploy supports speaker
vectors behind one environment variable; the app already has the place
where the vector would be read; nothing in production changes until a
speaker model is installed and the flag is set. Clustering is NOT
implemented in this phase — this document records what was measured and
proposes the design, as asked ("investigate and report first, implement
later").

## What is already there

- `scripts/vosk/asr_server.py` (our patched copy of vosk-server) reads
  `VOSK_SPK_MODEL_PATH`, loads `SpkModel` once, and calls
  `rec.SetSpkModel(spk_model)` on every recognizer. With a speaker model the
  per-utterance result carries `spk` (a 128-dimensional x-vector) and
  `spk_frames` (how many 10 ms frames the vector was computed from). Without
  the variable nothing changes.
- `scripts/vosk-up.sh` does not pass the variable yet, and `scripts/vosk-model.sh`
  installs language models into `/srv/citizens-vosk/models`; the speaker
  model (`vosk-model-spk-0.4`, 13.9 MB zip, Apache-2.0) fits the same
  directory and the same script.
- `citizens/services/live_captions.py`, `VoskSession._handle_message`,
  builds each caption line from the result's `text` and `result` (word
  timings) and leaves `speaker=None`. That is the hook: the vector arrives
  in the same JSON object as the line it belongs to.
- `citizens/services/speaking_live.py` (phase C3) already turns labelled
  lines into the anonymous distribution the facilitator's page shows, and
  the page says "not available with this transcription engine" when no
  line carries a label. Deepgram's labels feed it today; a Vosk label would
  feed it the same way.

## What was measured

Run on the dev host, inside a throwaway container of the deployed image
(`alphacep/kaldi-vosk-server:latest`), with `vosk-model-small-it-0.22` plus
`vosk-model-spk-0.4`, fed 16 kHz mono PCM in 0.2 s frames exactly like the
live path. Two real dev recordings (not kept, not stored anywhere; numbers
only): `a` = 60 s, one voice; `b` = 415 s, a table discussion.

| | a (60 s, one voice) | b (415 s, discussion) |
|---|---|---|
| utterances (endpointed by Vosk) | 7 | 70 |
| utterances with a vector | 7 (100 %) | 62 (89 %) |
| vector dimensions | 128 | 128 |
| utterance length, median / max | 2.3 s / 4.3 s | 2.1 s / 18.7 s |
| utterances ≥ 3 s | 2 / 7 | 24 / 70 |
| `spk_frames`, median | 225 (≈ 2.3 s) | 228 |
| decode speed with the speaker model | 2.8× realtime | 1.4× realtime¹ |

¹ measured while the frontend test suite was running on the same host;
the 60 s file, measured idle, is the better figure. Both are comfortably
above realtime, and the speaker model adds a few percent to a recognizer
that is already running — not a second pass.

Cosine similarity between vectors (only vectors from ≥ 1.5 s of speech):

| pairs | n | median | p10 | p90 |
|---|---|---|---|---|
| within `a` (same voice) | 10 | **0.57** | 0.52 | 0.66 |
| within `b` (several voices) | 741 | 0.28 | 0.03 | 0.65 |
| across `a` × `b` (different recordings) | 195 | **0.13** | 0.02 | 0.24 |

Reading: the same voice in the same room sits around 0.5–0.65; unrelated
voices around 0.1; a real discussion spreads between the two, which is
what a clustering step would separate. The upstream reference for this
model puts the same/different threshold around 0.5 (vosk's own
`test_speaker.py` uses cosine distance with a similar scale); our numbers
agree with that.

## Caveats found

- **Short utterances are noisy.** Vosk endpoints on pauses, so most
  utterances are 1–3 s; the model's own guidance is that vectors below
  ~1.5 s of speech are unreliable, and p10 within the single-voice file is
  still 0.52 while within the discussion p10 is 0.03. A design must only
  cluster vectors from long enough utterances (≥ 3 s, or merge consecutive
  utterances until ≥ 3 s) and leave the rest UNKNOWN.
- **Table microphones mix voices.** One phone in the middle of six people:
  a single utterance often contains two voices (an interruption, a
  "yes" over someone). Vectors of such utterances fall between clusters.
  Coverage — the share of speaking time that got a confident label — must
  be reported with the distribution, so "Voice A 70 %" over 30 % coverage
  is never read as a fact.
- **Not every utterance carries a vector** (62/70 in the discussion): the
  very short ones do not. Fine for a balance signal; it means coverage is
  structurally below 100 %.
- **Live path = Vosk only.** Whisper/Mistral have no speaker labels in
  streaming; Deepgram labels already. The capability flag stays per
  engine.

## Proposed design (not built in this phase)

1. **Transport.** `vosk-up.sh` gains `VOSK_SPEAKER_MODEL=vosk-model-spk-0.4`
   (optional): when the directory exists it passes `VOSK_SPK_MODEL_PATH`
   to the container; otherwise it says so and runs as today. The app does
   not need to know — it only sees `spk` in results when present.
2. **Reading.** `VoskSession._handle_message` keeps `spk` and `spk_frames`
   on the line as transient fields (never stored in `live_captions`
   history that becomes the transcript; never written to disk).
3. **Clustering, in memory, per table recording.** A small online
   clusterer in `speaking_live.py`: centroids with a running mean; a vector
   from ≥ 3 s of speech (`spk_frames ≥ 300`, or consecutive utterances
   merged) is assigned to the nearest centroid if cosine ≥ **0.5**, else it
   opens a new centroid when fewer than 6 exist; below 1.5 s it is UNKNOWN
   and counts only toward total time; centroids older than the rolling
   window decay. Labels are letters by order of first appearance (Voice A,
   B, C) — never names, never carried across recordings or sessions.
4. **Output.** The same `{voices, shares, largest_percent, coverage}`
   dictionary the facilitator page and the AI facilitator already consume,
   plus `coverage` (0–1) shown next to the bars; `live_speaking_balance`
   becomes true for Vosk when a speaker model is loaded.
5. **Nothing persists.** Vectors and centroids live only in the caption
   session object and die with it; the transcript of record is unchanged;
   the report keeps its final-transcript balance (`speaking.py`), which
   stays the authoritative figure.
6. **Thresholds to confirm on event audio** before shipping: assignment
   cosine 0.5 (0.45–0.55 range from this spike), minimum speech 3 s, max 6
   voices per table, window 5 minutes. A half-day of real table audio with
   known speakers would settle them; the spike script is at
   `scratchpad/vosk-spike/spike.py` in this session's notes and takes
   16 kHz mono WAVs.

## Cost

- Memory: the speaker model is ~14 MB on disk, a few tens of MB resident.
- CPU: within the same recognizer pass; no extra decode. The deployed
  container keeps its 900 MB cap.
- Code: ~150 lines (server flag, line fields, clusterer, capability flag),
  plus unit tests on synthetic vectors — a small, isolated change that can
  ship behind the flag whenever the thresholds are confirmed.
