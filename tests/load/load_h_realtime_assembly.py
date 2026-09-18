# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Test H: a real 30-minute orchestrated assembly — 10 devices, real speech, real STT.

load_g_single_assembly.py proves the PROTOCOL under contention: ten devices,
one assembly, barriers so the requests genuinely overlap. But it sends a
four-second 440 Hz sine tone in five chunks. Nothing in it exercises the part
an assembly actually depends on — thirty minutes of speech arriving ten seconds
at a time, ten caption sessions held open against a provider, a job runner
working through ten half-hour transcriptions, and an analysis that has to make
sense of what people said. docs/release-readiness.md listed exactly this as not
done.

This runs it for real. The audio is real: half-hour recordings from past
assemblies, already WebM/Opus at the phones' own bitrate, sliced back into
ten-second pieces and replayed at wall-clock speed. The transcription is real
Mistral. The instance is the live one.

WHAT THIS COSTS, every time you run it:
  * 300 minutes of audio streamed to Mistral realtime (live captions), plus
  * 300 minutes of batch transcription, plus
  * 11 mistral-large calls carrying half-hour transcripts.
It also writes a real assembly, ~290 MB of audio, transcripts and findings into
the live instance's storage. Both are why --yes exists.

    # once, before: the live container ships with 512 MB, which ten ffmpeg
    # decoders and ten websockets will not fit inside
    docker update --memory 2g --memory-swap 2g nc_app_citizens

    python3 tests/load/load_h_realtime_assembly.py --smoke   # 1 device, 1 min
    python3 tests/load/load_h_realtime_assembly.py --yes     # the real thing

    # after
    docker update --memory 512m --memory-swap 512m nc_app_citizens
"""

import argparse
import base64
import concurrent.futures
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

CONTAINER = "nc_app_citizens"
REPO = pathlib.Path("/root/NextCloud-Citizen")
SECRET_FILE = REPO / ".app_secret"
#: the assemblies belong to this Nextcloud user, so the test one shows up in
#: the same list as the real ones and its report can be opened in the UI
ORGANIZER = "alex"

DEVICES = 10
CHUNK_SECONDS = 10  # frontend/src/recorder/engine.ts CHUNK_INTERVAL_MS
ROUND_MINUTES = 30
CHUNKS = ROUND_MINUTES * 60 // CHUNK_SECONDS  # 180
HEARTBEAT_EVERY = 2  # chunks -> every 20 s, as the real engine does
CAPTION_POLL_EVERY = 2  # chunks -> every 20 s
SAMPLE_SECONDS = 30

#: the long run needs headroom for 10 ffmpeg decoders + 10 provider sockets
MIN_MEMORY_BYTES = 1_500_000_000

TIMINGS: dict[str, list[float]] = {}
FAILURES: list[str] = []
#: per device: how the live-caption strip looked each time we asked
CAPTIONS: dict[int, list[tuple[bool, str]]] = {}
SAMPLES: list[dict] = []
_LOCK = threading.Lock()
_STOP = threading.Event()


# --------------------------------------------------------------- plumbing


def sh(*args: str, check: bool = True) -> str:
    return subprocess.run(
        args, capture_output=True, text=True, check=check
    ).stdout.strip()


def discover_base() -> str:
    """The container's address on the Nextcloud docker network.

    Not published to the host, and the address changes when the network is
    recreated, so it is looked up rather than hardcoded.
    """
    ip = sh(
        "docker", "inspect", "-f",
        "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}", CONTAINER,
    ).split()[0]
    return f"http://{ip}:23000"


def appapi_headers(user: str = ORGANIZER) -> dict:
    """AppAPI's shared-secret triple.

    The live instance runs with auth ON (its NEXTCLOUD_URL is the real
    deployment), so every request — public recorder routes included — goes
    through AppAPIAuthMiddleware first. The username in the third header is
    what organizer routes see as the current user.
    """
    secret = SECRET_FILE.read_text().strip()
    return {
        "EX-APP-ID": "citizens",
        "EX-APP-VERSION": "1.0.0",
        "AUTHORIZATION-APP-API": base64.b64encode(
            f"{user}:{secret}".encode()
        ).decode(),
    }


BASE = ""  # set in main(), after the container is found


def api(method, path, data=None, token=None, raw=None, sha=None, phase=None,
        want_bytes=False, quiet=False, timeout=180):
    headers = appapi_headers()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if raw is not None:
        headers["Content-Type"] = "application/octet-stream"
        headers["X-Chunk-SHA256"] = sha
        body = raw
    elif data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data).encode()
    else:
        body = None
    req = urllib.request.Request(BASE + path, data=body, method=method, headers=headers)
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = response.read()
        return payload if want_bytes else (json.loads(payload) if payload else {})
    except urllib.error.HTTPError as exc:
        if not quiet:
            with _LOCK:
                FAILURES.append(f"{method} {path} -> {exc.code} {exc.read()[:200]!r}")
        raise
    finally:
        if phase:
            with _LOCK:
                TIMINGS.setdefault(phase, []).append(time.monotonic() - started)


#: mirrors frontend/src/recorder/engine.ts RETRY_BASE_MS and its doubling
RETRY_BASE_SECONDS = 3
UPLOAD_ATTEMPTS = 5


def upload_chunk(recording: str, seq: int, blob: bytes, bearer: str) -> bool:
    """Upload one chunk, retrying transient failures like the phone does.

    The real engine keeps the chunk in IndexedDB and retries with exponential
    backoff forever; the first version of this simulator gave up on the first
    hiccup, and two of ten devices silently stopped recording eight minutes in
    — a fault in the test, not the app. Re-uploading is safe: the server keys
    on (recording, sequence, sha) and answers `duplicate` rather than storing
    it twice.
    """
    delay = RETRY_BASE_SECONDS
    for attempt in range(UPLOAD_ATTEMPTS):
        last = attempt == UPLOAD_ATTEMPTS - 1
        try:
            api(
                "POST", f"/api/v1/public/recorder/recordings/{recording}/chunks/{seq}",
                token=bearer, raw=blob, sha=hashlib.sha256(blob).hexdigest(),
                phase="chunk", quiet=not last,
            )
            return True
        except urllib.error.HTTPError as exc:
            # 4xx other than 429 will not become true by repeating it
            if exc.code < 500 and exc.code != 429:
                return False
        except Exception:
            if last:
                with _LOCK:
                    FAILURES.append(f"chunk {seq} of {recording}: gave up after "
                                    f"{UPLOAD_ATTEMPTS} attempts")
        if not last and _STOP.wait(delay):
            return False
        delay = min(delay * 2, 30)
    return False


def wait(barrier):
    """Barrier that gives up rather than hanging the run (as in load_g)."""
    try:
        barrier.wait(timeout=120)
    except threading.BrokenBarrierError:
        raise
    except Exception:
        barrier.abort()
        raise


# ------------------------------------------------------------------ audio


def real_recordings() -> list[tuple[float, str]]:
    """Half-hour recordings from past assemblies, longest first.

    Real speech in the exact container and bitrate the phones produce, which is
    the whole point: a sine tone would prove the protocol and nothing about
    transcription, diarization or analysis.
    """
    listing = sh(
        "docker", "exec", CONTAINER, "sh", "-c",
        'for f in $(find /data/assembled -type f -name "*.webm"); do '
        'd=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f"); '
        'echo "$d $f"; done',
    )
    found = []
    for line in listing.splitlines():
        duration, _, path = line.partition(" ")
        try:
            if float(duration) >= 1500:  # 25 minutes or more
                found.append((float(duration), path))
        except ValueError:
            continue
    found.sort(reverse=True)
    return found


def prepare_audio(workdir: pathlib.Path, devices: int, minutes: int) -> list[list[bytes]]:
    """One chunk list per device: real speech cut into ten-second byte slices.

    Byte slices of a PREFIX of the file, not re-encoded segments —
    assemble_recording concatenates the chunks and remuxes with -c copy, so the
    server rebuilds exactly those bytes and the live decoder sees one
    continuous stream. Chunk 0 carries the container header, so order matters
    and a gap is fatal. Taking a prefix (rather than slicing the whole file
    into however many pieces we want) is what keeps a chunk worth ten seconds
    of audio whatever the run length — a one-minute smoke test must not send
    five-megabyte chunks.
    """
    sources = real_recordings()
    if not sources:
        raise SystemExit("no long recordings found in /data/assembled to replay")
    workdir.mkdir(parents=True, exist_ok=True)

    wanted_seconds = minutes * 60
    chunks = wanted_seconds // CHUNK_SECONDS
    per_device = []
    for index in range(devices):
        duration, source = sources[index % len(sources)]
        local = workdir / f"device{index + 1}.webm"
        if not local.exists():
            sh("docker", "cp", f"{CONTAINER}:{source}", str(local))
        blob = local.read_bytes()
        # opus is near-constant bitrate, so byte position tracks time closely
        keep = min(len(blob), int(len(blob) * wanted_seconds / duration))
        prefix = blob[:keep]
        size = len(prefix) // chunks + 1
        pieces = [p for i in range(chunks) if (p := prefix[i * size:(i + 1) * size])]
        per_device.append(pieces)
        print(
            f"  device {index + 1:>2}: {local.name} -> {len(pieces)} chunks "
            f"of ~{size / 1024:.0f} KB ({len(prefix) / 1e6:.1f} MB of {duration / 60:.0f}-min source)"
        )
    return per_device


# ------------------------------------------------------------- organizer


def create_assembly(devices: int, minutes: int) -> dict:
    stamp = time.strftime("%Y-%m-%d %H:%M")
    return api(
        "POST", "/api/v1/assemblies",
        {
            "name": f"TEST Carico {devices} dispositivi {stamp}",
            "language": "it",
            "recording_mode": "orchestrated",
            "default_table_count": devices,
            "rounds": [
                {
                    "title": "Prova di carico",
                    "question": "Come si potrebbe migliorare la mobilità in città?",
                    "duration_minutes": minutes,
                }
            ],
        },
    )


def token_from_url(url: str) -> str:
    return url.rsplit("/join/", 1)[1]


# ---------------------------------------------------------------- device


def device(index: int, token: str, round_id: str, chunks: list[bytes],
           barrier, t_zero: float) -> dict:
    """One table phone, replaying its recording at wall-clock speed.

    Barriers only at the moments where simultaneity is the thing being tested —
    everyone joining, everyone starting, everyone stopping when the facilitator
    calls time. In between the devices follow an absolute schedule instead: a
    barrier every ten seconds for half an hour would turn one slow request into
    a broken run, and real phones are not in lockstep anyway.
    """
    CAPTIONS[index] = []

    wait(barrier)
    session = api("POST", "/api/v1/public/join", {"token": token}, phase="join")
    bearer = session["session_token"]

    wait(barrier)
    recording = api(
        "POST", "/api/v1/public/recorder/start",
        {"round_id": round_id, "mime_type": "audio/webm"},
        token=bearer, phase="start",
    )["recording_id"]

    sent = 0
    for seq, blob in enumerate(chunks):
        if _STOP.is_set():
            break
        # absolute schedule: drift does not accumulate, and a slow upload is
        # absorbed rather than pushing every later chunk back
        due = t_zero + seq * CHUNK_SECONDS
        delay = due - time.monotonic()
        if delay > 0 and _STOP.wait(delay):
            break  # asked to stop while waiting for this chunk's slot
        if not upload_chunk(recording, seq, blob, bearer):
            # a gap makes everything after it undecodable, so stop here and
            # complete with the contiguous prefix — the salvage path the app
            # already models in salvage_total_chunks()
            with _LOCK:
                FAILURES.append(f"device {index}: stopped at chunk {seq}")
            break
        sent = seq + 1
        if seq % HEARTBEAT_EVERY == 0:
            try:
                api(
                    "POST", "/api/v1/public/recorder/heartbeat",
                    {"recording_id": recording, "recording_active": True, "armed": True,
                     "local_chunks": sent, "acked_chunks": sent, "storage_ok": True},
                    token=bearer, phase="heartbeat", quiet=True, timeout=30,
                )
            except Exception:
                pass  # the real client fires these and forgets them
        if seq % CAPTION_POLL_EVERY == 1:
            try:
                live = api(
                    "GET", f"/api/v1/public/recorder/recordings/{recording}/live",
                    token=bearer, phase="live", quiet=True, timeout=30,
                )
                with _LOCK:
                    CAPTIONS[index].append(
                        (bool(live.get("lines")), live.get("reason", ""))
                    )
            except Exception:
                pass  # captions are best effort, exactly as on the phone

    wait(barrier)
    result = api(
        "POST", f"/api/v1/public/recorder/recordings/{recording}/complete",
        {"total_chunks": sent}, token=bearer, phase="complete",
    )
    if result.get("missing_sequences"):
        with _LOCK:
            FAILURES.append(f"device {index}: missing {result['missing_sequences'][:5]}")
    return {"index": index, "recording_id": recording, "sent": sent,
            "state": result.get("state", "?")}


# ---------------------------------------------------------------- sampler


def container_memory() -> tuple[float, float]:
    raw = sh("docker", "stats", "--no-stream", "--format", "{{.MemUsage}}\t{{.CPUPerc}}",
             CONTAINER, check=False)
    used, _, cpu = raw.partition("\t")
    match = re.match(r"\s*([\d.]+)\s*([KMG])iB", used.split("/")[0])
    mib = 0.0
    if match:
        mib = float(match.group(1)) * {"K": 1 / 1024, "M": 1, "G": 1024}[match.group(2)]
    cpu_match = re.match(r"\s*([\d.]+)", cpu)
    return mib, float(cpu_match.group(1)) if cpu_match else 0.0


def sampler(round_id: str, devices: int) -> None:
    """Memory and monitor state through the run.

    A 30-minute test that only reports its end state cannot tell a leak from a
    clean run, and the memory ceiling is the open question here.
    """
    while not _STOP.wait(SAMPLE_SECONDS):
        mib, cpu = container_memory()
        entry = {"t": time.strftime("%H:%M:%S"), "mem_mib": mib, "cpu": cpu}
        try:
            monitor = api("GET", f"/api/v1/rounds/{round_id}/monitor")
            entry["ready"] = monitor.get("tables_ready")
            entry["recording"] = sum(
                1 for t in monitor.get("tables", [])
                if (t.get("recording") or {}).get("state") == "RECORDING"
            )
        except Exception:
            entry["ready"] = None
        with _LOCK:
            SAMPLES.append(entry)
        print(f"    [{entry['t']}] mem={mib:6.0f} MiB cpu={cpu:5.1f}% "
              f"recording={entry.get('recording')}/{devices} ready={entry.get('ready')}")


# ------------------------------------------------------------ processing


def wait_for_processing(recordings: list[dict], round_id: str, budget_seconds: int) -> dict:
    """Wait out the tail: assembly, then the sequential Mistral transcriptions.

    The job runner claims one job at a time, so ten half-hour transcriptions
    happen one after another however high the provider concurrency cap is.
    """
    deadline = time.monotonic() + budget_seconds
    states: dict[str, str] = {}
    while time.monotonic() < deadline:
        states = {}
        for entry in recordings:
            try:
                info = api(
                    "GET", f"/api/v1/recordings/{entry['recording_id']}/transcript",
                    quiet=True,
                )
                states[entry["recording_id"]] = "TRANSCRIBED" if info.get("segments") else "EMPTY"
            except urllib.error.HTTPError as exc:
                states[entry["recording_id"]] = f"HTTP{exc.code}"
        done = sum(1 for s in states.values() if s == "TRANSCRIBED")
        # transcription is only half the tail: the table analyses and then the
        # round clustering follow it, and reading the findings before those
        # land reports an assembly that produced almost nothing when in fact
        # it had not finished thinking yet
        analysed = 0
        summary = ""
        try:
            findings = api("GET", f"/api/v1/rounds/{round_id}/findings", quiet=True)
            analysed = sum(1 for t in findings.get("tables", []) if t.get("analyzed"))
            summary = findings.get("round_summary") or ""
        except urllib.error.HTTPError:
            pass
        mib, _ = container_memory()
        print(f"    transcribed {done}/{len(recordings)}  analysed {analysed}/{len(recordings)}"
              f"  round_summary={'yes' if summary else 'no'}  mem={mib:.0f} MiB")
        if done == len(recordings) and analysed == len(recordings) and summary:
            break
        time.sleep(20)
    return states


# ------------------------------------------------------------------ main


def summarize(assembly: dict, round_id: str, results: list[dict], elapsed: float,
              strict: bool) -> bool:
    print("\n" + "=" * 68)
    print(f"assembly : {assembly['id']}")
    print(f"name     : {assembly['name']}")
    print(f"elapsed  : {elapsed / 60:.1f} min")

    print("\n-- request latency by phase " + "-" * 40)
    for phase, values in sorted(TIMINGS.items()):
        values = sorted(values)
        p95 = values[min(len(values) - 1, int(len(values) * 0.95))]
        print(f"  {phase:<10} n={len(values):<5} median={values[len(values) // 2] * 1000:6.0f}ms "
              f"p95={p95 * 1000:7.0f}ms max={values[-1] * 1000:7.0f}ms")

    print("\n-- live captions under load " + "-" * 40)
    for index in sorted(CAPTIONS):
        polls = CAPTIONS[index]
        if not polls:
            continue
        with_lines = sum(1 for has, _ in polls if has)
        reasons: dict[str, int] = {}
        for _, reason in polls:
            if reason:
                reasons[reason] = reasons.get(reason, 0) + 1
        print(f"  device {index:>2}: {with_lines:>3}/{len(polls):>3} polls had captions "
              f"({100 * with_lines / len(polls):5.1f}%)  reasons={reasons or '{}'}")

    if SAMPLES:
        peak = max(s["mem_mib"] for s in SAMPLES)
        print("\n-- container " + "-" * 55)
        print(f"  peak memory {peak:.0f} MiB   (limit was "
              f"{int(sh('docker', 'inspect', '-f', '{{.HostConfig.Memory}}', CONTAINER)) / 1e6:.0f} MB)")

    print("\n-- transcripts " + "-" * 53)
    total_words = 0
    diarized = 0
    for entry in results:
        try:
            data = api("GET", f"/api/v1/recordings/{entry['recording_id']}/transcript",
                       quiet=True)
        except urllib.error.HTTPError:
            print(f"  device {entry['index']:>2}: no transcript")
            continue
        segments = data.get("segments", [])
        words = sum(len(s.get("text", "").split()) for s in segments)
        speakers = {s.get("speaker") for s in segments if s.get("speaker")}
        total_words += words
        diarized += 1 if len(speakers) >= 2 else 0
        print(f"  device {entry['index']:>2}: {len(segments):>4} segments, {words:>5} words, "
              f"{len(speakers)} voice(s)")

    print("\n-- analysis " + "-" * 56)
    findings = api("GET", f"/api/v1/rounds/{round_id}/findings")
    per_table = sum(len(t.get("findings", [])) for t in findings.get("tables", []))
    balance = findings.get("speaking_balance")
    print(f"  table findings: {per_table}")
    print(f"  cross-table   : {len(findings.get('cross_table', []))}")
    print(f"  round summary : {'yes' if findings.get('round_summary') else 'no'}")
    if balance:
        voices = ", ".join(f"{v['label']} {v['percent']}%" for v in balance["voices"])
        print(f"  speaking balance: {voices}")
    else:
        print("  speaking balance: none (no diarized speech)")

    pdf_ok = False
    try:
        # the final report only exists once the session is closed
        api("POST", f"/api/v1/assemblies/{assembly['id']}/close", {}, quiet=True)
    except urllib.error.HTTPError:
        pass
    try:
        pdf = api("GET", f"/api/v1/assemblies/{assembly['id']}/report.pdf", want_bytes=True)
        pdf_ok = pdf[:4] == b"%PDF"
        print(f"  report.pdf    : {len(pdf) / 1024:.0f} KB, valid={pdf_ok}")
    except urllib.error.HTTPError as exc:
        print(f"  report.pdf    : FAILED {exc.code}")

    print("\n-- failures " + "-" * 56)
    if FAILURES:
        for failure in FAILURES[:15]:
            print(f"  {failure}")
        if len(FAILURES) > 15:
            print(f"  … and {len(FAILURES) - 15} more")
    else:
        print("  none")

    # a one-minute smoke test legitimately yields no findings; a half-hour
    # discussion that produces none has not exercised what it was run for
    ok = not FAILURES and total_words > 0 and pdf_ok and (per_table > 0 or not strict)
    print("\n" + ("PASS" if ok else "FAIL"))
    auth = f"$(printf '{ORGANIZER}:%s' \"$(cat {SECRET_FILE})\" | base64 -w0)"
    print(
        "\nto delete the test data when you are done:\n"
        "  curl -X DELETE -H 'EX-APP-ID: citizens' -H 'EX-APP-VERSION: 1.0.0' \\\n"
        f'       -H "AUTHORIZATION-APP-API: {auth}" \\\n'
        f"       {BASE}/api/v1/assemblies/{assembly['id']}"
    )
    return ok


def run(devices: int, minutes: int, workdir: pathlib.Path) -> int:
    print(f"preparing real audio for {devices} device(s)…")
    audio = prepare_audio(workdir, devices, minutes)

    print("creating the assembly…")
    assembly = create_assembly(devices, minutes)
    round_id = assembly["rounds"][0]["id"]
    tokens = [token_from_url(inv["url"]) for inv in assembly["invites"]]
    print(f"  {assembly['id']}  round {round_id}  {len(tokens)} invites")

    barrier = threading.Barrier(devices)
    started = time.monotonic()
    sample_thread = threading.Thread(target=sampler, args=(round_id, devices), daemon=True)
    results: list[dict] = []

    try:
        # the facilitator starts the round: until it is ACTIVE the devices are
        # refused by the orchestrated gate in services/recording.py
        api("POST", f"/api/v1/rounds/{round_id}/start")
        sample_thread.start()
        t_zero = time.monotonic() + 5  # a moment for every thread to reach the barrier

        with concurrent.futures.ThreadPoolExecutor(max_workers=devices) as pool:
            futures = [
                pool.submit(device, i + 1, tokens[i], round_id, audio[i], barrier, t_zero)
                for i in range(devices)
            ]
            for future in futures:
                try:
                    results.append(future.result())
                except Exception as exc:
                    with _LOCK:
                        FAILURES.append(f"device thread: {type(exc).__name__}: {exc}")
    except KeyboardInterrupt:
        print("\ninterrupted — closing the round and letting devices finish")
        _STOP.set()
    finally:
        _STOP.set()
        try:
            api("POST", f"/api/v1/rounds/{round_id}/end")
        except urllib.error.HTTPError:
            pass

    recording_elapsed = time.monotonic() - started
    print(f"\nrecording phase done in {recording_elapsed / 60:.1f} min; "
          f"waiting for transcription and analysis…")
    # the transcriptions run one after another (single job worker), so the tail
    # scales with total audio, not with one recording
    budget = max(10 * 60, devices * minutes * 12)
    wait_for_processing(results, round_id, budget_seconds=budget)

    return 0 if summarize(assembly, round_id, results, time.monotonic() - started,
                          strict=minutes >= ROUND_MINUTES) else 1


def guard_memory() -> None:
    limit = int(sh("docker", "inspect", "-f", "{{.HostConfig.Memory}}", CONTAINER))
    if limit and limit < MIN_MEMORY_BYTES:
        raise SystemExit(
            f"the container is capped at {limit / 1e6:.0f} MB. Ten caption sessions "
            f"means ten ffmpeg decoders and ten websockets; run\n"
            f"  docker update --memory 2g --memory-swap 2g {CONTAINER}\n"
            f"first (it applies live on cgroup v2), and put it back afterwards."
        )


def main() -> int:
    global BASE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true",
                        help="one device, one minute — proves Mistral is configured")
    parser.add_argument("--yes", action="store_true",
                        help="required for the full run: it spends real money")
    parser.add_argument("--devices", type=int, default=DEVICES)
    args = parser.parse_args()

    BASE = discover_base()
    print(f"target: {BASE} ({CONTAINER})")

    workdir = pathlib.Path("/tmp/citizens-load-h")
    if args.smoke:
        print("SMOKE: 1 device, 6 chunks (~1 minute of real speech)\n")
        return run(1, 1, workdir)

    if not args.yes:
        print(
            f"\nThis runs a REAL {ROUND_MINUTES}-minute assembly on the live instance:\n"
            f"  * {args.devices} devices x {ROUND_MINUTES} min = "
            f"{args.devices * ROUND_MINUTES} minutes of audio\n"
            f"  * billed twice to Mistral (live captions + final transcription)\n"
            f"  * plus {args.devices + 1} mistral-large analysis calls\n"
            f"  * writes a real assembly and ~290 MB of audio into /data\n"
            f"  * total wall clock, including the processing tail: 1-1.5 hours\n\n"
            f"Run --smoke first. Then re-run with --yes.",
            file=sys.stderr,
        )
        return 2

    guard_memory()
    print(f"FULL RUN: {args.devices} devices, {ROUND_MINUTES} minutes, real Mistral\n")
    return run(args.devices, ROUND_MINUTES, workdir)


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        _STOP.set()
