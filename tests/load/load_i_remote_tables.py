#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Test I: ten table phones against SOMEBODY ELSE'S Nextcloud, from the QR links alone.

Tests F, G and H all need this machine: they discover the container with
`docker inspect`, sign every request with the ExApp's shared secret, and drive
the round through the organizer API. None of that exists when the instance
belongs to another organisation — and that is exactly when a ten-table
rehearsal matters most, because their proxy, their PHP workers and their
speech-to-text account are the parts we have never exercised.

A phone needs none of it. Everything a table does goes through the PUBLIC
recorder API, and a QR link carries the whole address:

    https://host/index.php/apps/app_api/proxy/citizens/recorder.html#/join/<token>
    └────────────── the API base, once /recorder.html is stripped ──┘  └ token ┘

So this script takes the links — from a file, from the arguments, or straight
out of the printed QR sheet, which puts the address in text under each code —
and replays real speech at wall-clock speed, ten seconds at a time, with the
heartbeats, the status polls, the caption polls and the device log that a real
phone sends. Two tables can simulate the 0.6.2 "the screen went off"
interruption: they stop for a while and resume in the SAME recording, in a new
segment, which is the part of 0.6.2 that only a server can confirm.

What it cannot do: press "Start round". The AppAPI proxy authenticates every
non-public route with a Nextcloud session cookie, which a script has none of.
So it waits, printing a banner, until the round goes ACTIVE — the facilitator
presses the button whenever they are ready, no countdown to coordinate.

WHAT A RUN COSTS THE OTHER ORGANISATION, every time:
  * their speech-to-text account, twice over: live captions while recording,
    then the final transcription (tables x minutes, so 10 x 40 = 800 minutes
    of billed audio for a full run);
  * one analysis call per table plus one for the round;
  * the audio on their disk (~350 KB per table-minute) until somebody deletes
    the assembly, which is the last step of the runbook and not optional;
  * our own recorded voices processed by their sub-processor.
Ask first. The `--yes` text says all of it out loud.

    # arithmetic only: no network, no ffmpeg
    python3 tests/load/load_i_remote_tables.py --plan-only --minutes 8

    # prove the script here first, against our own instance, end to end
    python3 tests/load/load_i_remote_tables.py --seed-local --minutes 3 --interrupt 2

    # then, someone else's instance, from their QR sheet
    python3 tests/load/load_i_remote_tables.py --links-pdf sheet.pdf --minutes 8

Standard library only, so it also runs from a laptop with no repo checkout —
except `--seed-local` and the default audio source, which need this host's
docker. See docs/remote-load-test.md for the operator's side.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import json
import os
import pathlib
import queue
import re
import signal
import socket
import ssl
import statistics
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Constants mirroring the real recorder. Each one names where it comes from:
# a load test that drifts from the phone stops measuring the phone.
# ---------------------------------------------------------------------------

CHUNK_SECONDS = 10  # engine.ts CHUNK_INTERVAL_MS
HEARTBEAT_SECONDS = 20  # engine.ts HEARTBEAT_MS
STATUS_POLL_SECONDS = 8  # RecordingScreen.vue roundPollTimer — the poll that
#                          made six OCS calls per phone before 0.6.2
LIVE_POLL_SECONDS = 20  # the phone polls captions every 6 s; gentler here
LOG_SHIP_SECONDS = 15  # logger.ts SHIP_INTERVAL_MS
SYNC_POLL_SECONDS = 3  # engine.ts pollUntilProcessed
RETRY_BASE_SECONDS = 3  # engine.ts RETRY_BASE_MS
RETRY_MAX_SECONDS = 60  # engine.ts RETRY_MAX_MS
MAX_CHUNK_BYTES = 5 * 1024 * 1024  # services/recording.py MAX_CHUNK_BYTES
MAX_LOG_ENTRIES = 200  # public_recorder.py LogsIn
#: services/recording.py STALLED_DEVICE_SECONDS — past this the server treats
#: the phone as gone, releases the table, and stops reporting its recording.
#: An interruption longer than this is a different test (device replacement).
MAX_INTERRUPT_SECONDS = 110
#: the first build whose server understands X-Chunk-Segment (migration 0023)
SEGMENT_VERSION = (0, 6, 2)
#: states in which the server has validated the audio — engine.ts COMPLETED_STATES
COMPLETED_STATES = {
    "AUDIO_READY", "TRANSCRIBING", "TRANSCRIBED", "TRANSCRIPTION_FAILED",
    "ANALYZING", "READY_FOR_REVIEW", "REVIEWED", "ANALYSIS_FAILED",
}
#: our own test recordings, by assembly name. NOT a duration glob: /data/assembled
#: also holds real assemblies, and uploading those voices to another
#: organisation's instance is not ours to do.
TEST_ASSEMBLY_PATTERN = r"(?i)^(testcasa|testnavigli|politest|testeumans|testsimo)"
AUDIO_BITRATE = "48k"  # speech, transparent for transcription, a third of a phone's
#: past this the tables are mostly hearing each other's audio and the analysis
#: stops meaning anything, even though the protocol would be fine
MAX_LOOP_COPIES = 6

#: the server letting go of an idle keep-alive. Not a failure: retry on a new
#: connection, count the reconnect, and do not put it in the fault list — on a
#: forty-minute run every table would otherwise collect a dozen of them.
IDLE_TEARDOWN = (
    http.client.RemoteDisconnected,
    http.client.BadStatusLine,
    BrokenPipeError,
    ssl.SSLEOFError,
    ssl.SSLZeroReturnError,
)

log_lock = threading.Lock()


def say(message: str = "") -> None:
    with log_lock:
        print(message, flush=True)


def stamp() -> str:
    return time.strftime("%H:%M:%S", time.gmtime())


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")  # public_recorder.py JoinIn


def mask(token: str) -> str:
    """Tokens are credentials for somebody's assembly: never whole, anywhere."""
    return f"{token[:4]}…{token[-2:]} ({len(token)})" if len(token) > 8 else "…"


@dataclass(frozen=True)
class Link:
    base: str
    token: str
    #: the table number printed beside it on the QR sheet, when we know it —
    #: the server's own answer at join is what we trust
    printed_table: int | None = None

    @property
    def host(self) -> str:
        return urllib.parse.urlsplit(self.base).netloc


def parse_link(raw: str, printed_table: int | None = None) -> Link:
    """A QR link to (API base, token).

    The page's bootstrap sets __CITIZENS_RECORDER_BASE__ by cutting the path at
    '/recorder', and appBase() strips that again (recorder_page.py:55-60,
    api.ts:115-119) — so the base is the link with '/recorder.html' removed.
    Never assume '/index.php/apps/app_api/proxy/…': a HaRP deployment serves
    the same app under '/exapps/citizens/…'.
    """
    raw = raw.strip()
    if not raw:
        raise ValueError("empty link")
    url, _, fragment = raw.partition("#")
    if not fragment.startswith("/join/"):
        raise ValueError("not a join link (no '#/join/<token>')")
    token = fragment[len("/join/"):].strip().strip("/")
    if not TOKEN_RE.match(token):
        raise ValueError("the token is not a recorder token")
    split = urllib.parse.urlsplit(url)
    if split.scheme not in ("http", "https") or not split.netloc:
        raise ValueError(f"not an address: {url[:60]}")
    path = split.path
    for suffix in ("/recorder.html", "/recorder/", "/recorder"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    else:
        raise ValueError("the link does not point at the recorder page")
    base = urllib.parse.urlunsplit((split.scheme, split.netloc, path.rstrip("/"), "", ""))
    return Link(base=base, token=token, printed_table=printed_table)


def links_from_pdf(path: pathlib.Path) -> list[Link]:
    """The printed QR sheet, read back.

    qr_sheet.py:101 puts the address in 6-point text under each code, so the
    sheet the admins already sent is a machine-readable list — no transcribing
    tokens by hand. `-raw` keeps fpdf2's drawing order (table, then its
    address), which `-layout` interleaves across the two columns.
    """
    try:
        text = subprocess.run(
            ["pdftotext", "-raw", str(path), "-"],
            capture_output=True, text=True, check=True, timeout=120,
        ).stdout
    except FileNotFoundError as exc:
        raise SystemExit("pdftotext is not installed (apt install poppler-utils)") from exc
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"pdftotext could not read {path}: {exc.stderr[:200]}") from exc
    # multi_cell wraps the address, so '…recorder.html#/' and 'join/<token>'
    # land on separate lines
    glued = re.sub(r"#/\s+join/", "#/join/", text)
    found: dict[int, Link] = {}
    for number, url in re.findall(
        r"TABLE (\d+).*?(https://\S+#/join/[A-Za-z0-9_-]{16,128}|http://\S+#/join/[A-Za-z0-9_-]{16,128})",
        glued, re.S,
    ):
        table = int(number)
        if table not in found:
            found[table] = parse_link(url, printed_table=table)
    if not found:
        raise SystemExit(f"no join links found in {path}")
    return [found[number] for number in sorted(found)]


def read_links(files: list[str], pdfs: list[str], positionals: list[str]) -> list[Link]:
    links: list[Link] = []
    for pdf in pdfs:
        links.extend(links_from_pdf(pathlib.Path(pdf)))
    for name in files:
        for line in pathlib.Path(name).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                links.append(parse_link(line))
    for raw in positionals:
        links.append(parse_link(raw))
    if not links:
        raise SystemExit("no links given: use --links-pdf, --links or positional arguments")
    bases = {link.base for link in links}
    if len(bases) > 1:
        raise SystemExit(f"the links point at {len(bases)} different servers: {sorted(bases)}")
    seen: set[str] = set()
    unique: list[Link] = []
    for link in links:
        if link.token in seen:
            say(f"  ignoring a repeated link ({mask(link.token)})")
            continue
        seen.add(link.token)
        unique.append(link)
    return unique


# ---------------------------------------------------------------------------
# HTTP: one keep-alive connection per thread, like a phone's.
# ---------------------------------------------------------------------------


@dataclass
class Reply:
    status: int
    body: dict | bytes | None
    seconds: float
    fault: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def detail(self) -> str:
        if self.fault:
            return self.fault
        if isinstance(self.body, dict):
            return str(self.body.get("detail", ""))[:200]
        return ""


def classify(exc: BaseException) -> str:
    if isinstance(exc, socket.timeout | TimeoutError):
        return "timeout"
    # before ConnectionResetError, which it subclasses: a keep-alive the server
    # closed between requests is ordinary, a reset mid-transfer is not. So is
    # an SSL end-of-file and a broken pipe: nginx and Apache both hang up on
    # idle connections, and a phone would simply open another.
    if isinstance(exc, IDLE_TEARDOWN):
        return "conn_closed"
    if isinstance(exc, ConnectionResetError):
        return "conn_reset"
    if isinstance(exc, ConnectionRefusedError):
        return "conn_refused"
    if isinstance(exc, ssl.SSLError):
        return "tls"
    if isinstance(exc, socket.gaierror):
        return "dns"
    if isinstance(exc, http.client.HTTPException):
        return "protocol"
    return type(exc).__name__


class Metrics:
    """Latency and outcome per endpoint, plus a per-minute view.

    The per-minute buckets are the point: a run whose median is fine and whose
    worst minute is 40 seconds long is a run that froze, and an average hides
    exactly that.
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.seconds: dict[str, list[float]] = {}
        self.outcomes: dict[str, dict[str, int]] = {}
        self.minutes: dict[int, dict[str, int]] = {}
        self.slow: list[tuple[str, str, float]] = []
        self.faults: list[tuple[str, str, str, str]] = []
        self.started = time.time()

    def record(self, endpoint: str, reply: Reply) -> None:
        if reply.fault:
            outcome = reply.fault
        elif reply.ok:
            outcome = "ok"
        elif reply.status >= 500:
            outcome = "5xx"
        else:
            outcome = f"{reply.status}"
        minute = int((time.time() - self.started) // 60)
        with self.lock:
            self.seconds.setdefault(endpoint, []).append(reply.seconds)
            self.outcomes.setdefault(endpoint, {}).setdefault(outcome, 0)
            self.outcomes[endpoint][outcome] += 1
            bucket = self.minutes.setdefault(minute, {})
            bucket[outcome] = bucket.get(outcome, 0) + 1
            bucket["n"] = bucket.get("n", 0) + 1
            bucket["worst"] = max(bucket.get("worst", 0.0), reply.seconds)
            if reply.seconds >= 10:
                self.slow.append((stamp(), endpoint, reply.seconds))
            if outcome not in ("ok",) and not outcome.startswith("4"):
                self.faults.append((stamp(), endpoint, outcome, reply.detail()))

    def percentiles(self, endpoint: str) -> tuple[float, float, float]:
        values = sorted(self.seconds.get(endpoint, []))
        if not values:
            return (0.0, 0.0, 0.0)
        index = min(len(values) - 1, int(len(values) * 0.95))
        return (statistics.median(values), values[index], values[-1])


class Breaker:
    """Stop when the server is clearly in trouble.

    This runs against a production instance that belongs to somebody else. If
    it starts failing we have the answer already; continuing for another seven
    minutes only prolongs an outage for their other users.
    """

    def __init__(self, server_errors: int, consecutive_slow: int, slow_seconds: float) -> None:
        self.limit = server_errors
        self.slow_limit = consecutive_slow
        self.slow_seconds = slow_seconds
        self.lock = threading.Lock()
        self.server_errors = 0
        self.consecutive_slow = 0
        self.reason = ""

    def note(self, reply: Reply) -> None:
        with self.lock:
            if reply.status >= 500 or reply.fault in ("timeout", "conn_reset", "conn_closed"):
                self.server_errors += 1
            if reply.seconds >= self.slow_seconds:
                self.consecutive_slow += 1
            else:
                self.consecutive_slow = 0
            if not self.reason:
                if self.server_errors >= self.limit:
                    self.reason = (
                        f"{self.server_errors} server errors or dropped connections "
                        f"(limit {self.limit})"
                    )
                elif self.consecutive_slow >= self.slow_limit:
                    self.reason = (
                        f"{self.consecutive_slow} requests in a row slower than "
                        f"{self.slow_seconds:.0f} s"
                    )

    def tripped(self) -> str:
        with self.lock:
            return self.reason


class Client:
    """One connection, reused. Not thread-safe: make one per thread."""

    def __init__(self, base: str, metrics: Metrics, breaker: Breaker | None = None,
                 timeout: float = 60.0) -> None:
        split = urllib.parse.urlsplit(base)
        self.host = split.netloc
        self.prefix = split.path.rstrip("/")
        self.https = split.scheme == "https"
        self.timeout = timeout
        self.metrics = metrics
        self.breaker = breaker
        self.connection: http.client.HTTPConnection | None = None
        self.connects = 0
        self.reconnects = 0

    def _connect(self) -> http.client.HTTPConnection:
        if self.connection is None:
            if self.https:
                self.connection = http.client.HTTPSConnection(self.host, timeout=self.timeout)
            else:
                self.connection = http.client.HTTPConnection(self.host, timeout=self.timeout)
            self.connects += 1
        return self.connection

    def close(self) -> None:
        if self.connection is not None:
            try:
                self.connection.close()
            except Exception:
                pass
            self.connection = None

    def call(self, method: str, path: str, *, json_body: dict | None = None,
             raw: bytes | None = None, headers: dict | None = None, bearer: str = "",
             endpoint: str = "", want_bytes: bool = False,
             timeout: float | None = None) -> Reply:
        """One request. Returns a Reply — never raises for an HTTP status."""
        endpoint = endpoint or path
        sent_headers = dict(headers or {})
        if bearer:
            sent_headers["Authorization"] = f"Bearer {bearer}"
        body: bytes | None = None
        if raw is not None:
            body = raw
            sent_headers.setdefault("Content-Type", "application/octet-stream")
        elif json_body is not None:
            body = json.dumps(json_body).encode()
            sent_headers["Content-Type"] = "application/json"
        sent_headers["Accept"] = "application/json"
        sent_headers["User-Agent"] = "citizens-load-i"
        started = time.monotonic()
        reply: Reply
        for attempt in (0, 1):  # a dropped keep-alive is not a server error
            try:
                connection = self._connect()
                if timeout is not None:
                    connection.timeout = timeout
                connection.request(method, self.prefix + path, body=body, headers=sent_headers)
                response = connection.getresponse()
                payload = response.read()
                if want_bytes:
                    parsed: dict | bytes | None = payload
                else:
                    try:
                        parsed = json.loads(payload) if payload else {}
                    except ValueError:
                        parsed = {"detail": payload[:200].decode("utf-8", "replace")}
                reply = Reply(response.status, parsed, time.monotonic() - started)
                break
            except (*IDLE_TEARDOWN, ConnectionResetError) as exc:
                self.close()
                if attempt == 0:
                    self.reconnects += 1
                    continue
                reply = Reply(0, None, time.monotonic() - started, classify(exc))
                break
            except Exception as exc:  # timeout, TLS, DNS, anything
                self.close()
                reply = Reply(0, None, time.monotonic() - started, classify(exc))
                break
        self.metrics.record(endpoint, reply)
        if self.breaker is not None:
            self.breaker.note(reply)
        return reply


# ---------------------------------------------------------------------------
# Which build is over there
# ---------------------------------------------------------------------------


def version_tuple(text: str) -> tuple[int, ...] | None:
    match = re.match(r"(\d+)\.(\d+)\.(\d+)", text.strip())
    return tuple(int(part) for part in match.groups()) if match else None


def deployed_version(client: Client) -> str:
    """The version the recorder page declares — readable with no credentials.

    It is what AppAPI registered, not proof of the running code, so it gates
    the run and nothing more; the behavioural proof is whether the segments
    come back joined.
    """
    reply = client.call("GET", "/recorder.html", endpoint="recorder.html", want_bytes=True)
    if not reply.ok or not isinstance(reply.body, bytes):
        return ""
    match = re.search(rb"citizens-recorder\.js\?v=([0-9][0-9A-Za-z.\-]*)", reply.body)
    return match.group(1).decode() if match else ""


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------


@dataclass
class Source:
    path: str
    seconds: float
    assembly: str


def ffprobe_seconds(path: pathlib.Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, timeout=120,
    )
    try:
        return float(out.stdout.strip())
    except ValueError as exc:
        raise SystemExit(f"ffprobe could not read {path}: {out.stderr[:200]}") from exc


def source_recordings(container: str, pattern: str) -> list[Source]:
    """Our own test recordings, chosen by ASSEMBLY NAME.

    load_h picks by duration, which on this host would also pick up real
    citizens' assemblies. Those are not ours to send to another organisation's
    server, where their speech-to-text account would transcribe them.
    """
    script = (
        "import json,sqlite3;"
        "c=sqlite3.connect('file:/data/citizens.db?mode=ro',uri=True);"
        "print(json.dumps([list(r) for r in c.execute("
        "\"select a.name, r.duration_seconds, r.canonical_audio_path from recordings r \""
        "\"join assemblies a on a.id=r.assembly_id where r.canonical_audio_path is not null \""
        "\"and r.duration_seconds >= 300 order by r.duration_seconds desc\")]))"
    )
    out = subprocess.run(
        ["docker", "exec", container, "python3", "-c", script],
        capture_output=True, text=True, timeout=120,
    )
    if out.returncode != 0:
        raise SystemExit(f"could not read {container}'s database: {out.stderr[-200:]}")
    wanted = re.compile(pattern)
    chosen: list[Source] = []
    seen: set[int] = set()
    for name, seconds, path in json.loads(out.stdout):
        if not wanted.search(name):
            continue
        key = int(seconds * 1000)  # the load_h replays duplicate earlier audio
        if key in seen:
            continue
        seen.add(key)
        chosen.append(Source(path=f"/data/{path}", seconds=float(seconds), assembly=name))
    return chosen


def mean_volume_db(path: pathlib.Path) -> float:
    """Average level of a file, as ffmpeg's volumedetect reports it.

    Digital silence comes back around -91 dB, ordinary recorded speech between
    -40 and -25. The number is what tells a dead recording from a quiet one.
    """
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path), "-af", "volumedetect",
         "-f", "null", os.devnull],
        capture_output=True, text=True, timeout=1800,
    )
    match = re.search(r"mean_volume:\s*(-?[\d.]+) dB", out.stderr)
    return float(match.group(1)) if match else -999.0


@dataclass
class Part:
    """One source, re-encoded to the common format the loop is built from."""
    path: pathlib.Path
    seconds: float
    mean_db: float
    assembly: str


#: below this a recording holds no speech at all. One of our own test
#: recordings is exactly this: six minutes at -91 dB, which became a table's
#: whole window in the eight-minute run and produced no captions and no
#: transcript. A load test must not ship silence and call it audio.
SILENCE_FLOOR_DB = -60.0


def part_name(workdir: pathlib.Path, source: str, bitrate: str, normalised: bool) -> pathlib.Path:
    """Fingerprint of (source, bitrate, normalisation) — same discipline as
    cut_name, for the same reason: a cached file from a run with different
    settings must never be mistaken for this run's."""
    key = f"{source}|{bitrate}|{'norm' if normalised else 'raw'}"
    return workdir / f"part-{hashlib.sha256(key.encode()).hexdigest()[:12]}.webm"


def drop_silent(parts: list[Part], floor_db: float = SILENCE_FLOOR_DB) -> tuple[list[Part], list[Part]]:
    """(kept, dropped). Pure, so the rule is testable without any audio."""
    kept = [part for part in parts if part.mean_db > floor_db]
    return kept, [part for part in parts if part.mean_db <= floor_db]


def prepare_parts(sources: list[Source], container: str,
                  workdir: pathlib.Path) -> tuple[list[Part], list[Part]]:
    """Every source, re-encoded to one format and levelled, silence discarded.

    Re-encoding is not optional: the sources run from 75 to 130 kbps and the
    concat demuxer cannot copy those together. Levelling is not either — twelve
    decibels between sources meant a table receiving speech at the edge of
    audibility, which is a confound on one of the things this test measures
    (how many tables get live captions). EBU R128 at -20 LUFS, one pass.
    """
    parts: list[Part] = []
    for index, source in enumerate(sources):
        part = part_name(workdir, source.path, AUDIO_BITRATE, normalised=True)
        if not part.exists():
            copied = workdir / f"raw-{index}.webm"
            if not copied.exists():
                subprocess.run(["docker", "cp", f"{container}:{source.path}", str(copied)],
                               check=True, capture_output=True, timeout=600)
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-i", str(copied),
                 "-af", "loudnorm=I=-20:TP=-2:LRA=11",
                 "-c:a", "libopus", "-b:a", AUDIO_BITRATE, "-ac", "1", "-ar", "48000",
                 str(part)],
                check=True, capture_output=True, timeout=3600,
            )
            copied.unlink(missing_ok=True)
        # Measuring means decoding the whole file, so the answer is cached
        # beside it: without this, every run spent minutes re-measuring three
        # hours of audio it had already measured, with the operators waiting.
        receipt = part.with_suffix(".json")
        try:
            measured = json.loads(receipt.read_text())
        except (OSError, ValueError):
            measured = {"seconds": ffprobe_seconds(part), "mean_db": mean_volume_db(part)}
            receipt.write_text(json.dumps(measured))
        parts.append(Part(part, float(measured["seconds"]), float(measured["mean_db"]),
                          source.assembly))
    return drop_silent(parts)


def concat_loop(parts: list[Part], workdir: pathlib.Path,
                copies: int) -> tuple[pathlib.Path, float]:
    """The material every window is cut from: the parts, end to end, `copies`
    times over. Cached, because concatenating hours of audio is not free."""
    key = "|".join(str(part.path) for part in parts) + f"|{copies}"
    loop = workdir / f"loop-{hashlib.sha256(key.encode()).hexdigest()[:12]}.webm"
    if loop.exists():
        return loop, ffprobe_seconds(loop)
    listing = loop.with_suffix(".txt")
    listing.write_text("".join(f"file '{part.path}'\n" for part in parts * copies))
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
         "-i", str(listing), "-c", "copy", str(loop)],
        check=True, capture_output=True, timeout=3600,
    )
    seconds = ffprobe_seconds(loop)
    expected = sum(part.seconds for part in parts) * copies
    if abs(seconds - expected) > max(2.0, expected * 0.01):
        raise SystemExit(
            f"the concatenation lost audio: {seconds:.0f}s against {expected:.0f}s expected"
        )
    return loop, seconds


def tone_file(workdir: pathlib.Path, seconds: float, index: int) -> pathlib.Path:
    path = cut_name(workdir, pathlib.Path(f"tone-{index}"), 0.0, seconds)
    if not path.exists():
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
             "-i", f"sine=frequency={330 + index * 20}:duration={seconds:.3f}",
             "-c:a", "libopus", "-b:a", AUDIO_BITRATE, "-ac", "1", str(path)],
            check=True, capture_output=True, timeout=600,
        )
    return path


def cut_name(workdir: pathlib.Path, source: pathlib.Path, offset: float,
             seconds: float) -> pathlib.Path:
    """A filename that is the window it holds.

    Naming these `table-3-seg0.webm` cost a real run: a three-minute validation
    left its cuts in the workdir, and an eight-minute run against another
    server reused them — the right number of chunks at the right cadence, with
    40% of the audio. The name is a fingerprint of (material, offset, length)
    now, so a different window can only ever be a different file.
    """
    key = f"{source}|{offset:.3f}|{seconds:.3f}"
    return workdir / f"cut-{hashlib.sha256(key.encode()).hexdigest()[:12]}.webm"


def cut_window(loop: pathlib.Path, offset: float, seconds: float,
               out: pathlib.Path) -> tuple[pathlib.Path, float]:
    """A window of the loop, with its own container header.

    Copied, not re-encoded, so the bytes stay the ones a phone would send —
    which means the cut lands on a packet boundary and the result is a second
    or two longer than asked. The MEASURED duration is what the server will
    report, so it is what we return; computing it would build slack into every
    later comparison.
    """
    if not out.exists():
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", f"{offset:.3f}", "-t", f"{seconds:.3f}",
             "-i", str(loop), "-c", "copy", str(out)],
            check=True, capture_output=True, timeout=1800,
        )
    return out, ffprobe_seconds(out)


@dataclass(frozen=True)
class Piece:
    """One chunk, as bytes on disk and as the receipt the server will hold."""
    offset: int
    length: int
    sha256: str


def slice_pieces(path: pathlib.Path, count: int) -> list[Piece]:
    """Byte slices of one continuous stream — the shape a MediaRecorder emits.

    Chunk 0 carries the container header and the rest continue it, so order
    matters and a gap is fatal: the server concatenates them back (audio.py
    _write_raw_stream) and remuxes with -c copy. Hashing here rather than at
    send time also gives us the manifest the server will publish, so a retry
    is byte-identical by construction.
    """
    data = path.read_bytes()
    if count < 1:
        raise ValueError("a recording needs at least one chunk")
    size = len(data) // count + 1
    pieces: list[Piece] = []
    for index in range(count):
        blob = data[index * size:(index + 1) * size]
        if not blob:
            break
        if len(blob) > MAX_CHUNK_BYTES:
            raise SystemExit(f"{path.name}: a {len(blob)} byte chunk is over the 5 MiB limit")
        pieces.append(Piece(index * size, len(blob), hashlib.sha256(blob).hexdigest()))
    return pieces


def manifest_of(pieces: list[Piece]) -> tuple[str, int]:
    """The receipt audio.py:141-145 builds after assembling, computed here.

    `sha256("{seq}:{size}:{sha}\\n" for every chunk)` plus the byte total. The
    phone checks exactly this (engine.ts markServerComplete), and it is the
    strongest thing an outside observer can ask for: not "about the right
    length" but "the same bytes, in the same order".
    """
    digest = hashlib.sha256()
    total = 0
    for seq, piece in enumerate(pieces):
        digest.update(f"{seq}:{piece.length}:{piece.sha256}\n".encode())
        total += piece.length
    return digest.hexdigest(), total


# ---------------------------------------------------------------------------
# The schedule — pure, and the whole of the segment bookkeeping
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChunkSpec:
    seq: int
    segment: int
    due: float  # seconds after the round starts
    piece: int  # index into that segment's piece list


@dataclass
class Plan:
    specs: list[ChunkSpec]
    #: seconds of audio to cut for each segment
    segment_seconds: list[float]
    #: where the interruption starts and how long it lasts (0 when there is none)
    interrupt_at: float = 0.0
    gap: float = 0.0

    @property
    def segments(self) -> int:
        return len(self.segment_seconds)

    def pieces_in(self, segment: int) -> int:
        return sum(1 for spec in self.specs if spec.segment == segment)


def plan_chunks(minutes: float, interrupt_at: float = 0.0, gap: float = 0.0) -> Plan:
    """What a table sends, and when.

    A MediaRecorder started with a ten-second timeslice delivers its first blob
    at +10 s, not at zero, and its last one is short — whatever was buffered
    when stop() was called. An interruption adds a second short blob (the flush
    of the session that died) and then a new session whose sequence numbers
    CONTINUE: one recording, two segments, no gap in the sequence, because the
    gap is in time, not in the numbering.
    """
    total = minutes * 60
    if interrupt_at and not 0 < interrupt_at < total:
        raise ValueError("the interruption has to fall inside the round")
    if gap > MAX_INTERRUPT_SECONDS:
        raise ValueError(
            f"an interruption of {gap:.0f}s outlives the server's patience "
            f"(STALLED_DEVICE_SECONDS is {MAX_INTERRUPT_SECONDS}s: the table would be released)"
        )
    specs: list[ChunkSpec] = []
    seq = 0
    if not interrupt_at:
        due = float(CHUNK_SECONDS)
        piece = 0
        while due < total:
            specs.append(ChunkSpec(seq, 0, due, piece))
            seq += 1
            piece += 1
            due += CHUNK_SECONDS
        specs.append(ChunkSpec(seq, 0, total, piece))  # the short final blob
        return Plan(specs, [total])

    # segment 0, up to the interruption
    due = float(CHUNK_SECONDS)
    piece = 0
    while due < interrupt_at:
        specs.append(ChunkSpec(seq, 0, due, piece))
        seq += 1
        piece += 1
        due += CHUNK_SECONDS
    specs.append(ChunkSpec(seq, 0, interrupt_at, piece))  # flush of the lost session
    seq += 1
    first = interrupt_at

    # segment 1, from the moment the microphone comes back
    resumed = interrupt_at + gap
    due = resumed + CHUNK_SECONDS
    piece = 0
    while due < total:
        specs.append(ChunkSpec(seq, 1, due, piece))
        seq += 1
        piece += 1
        due += CHUNK_SECONDS
    specs.append(ChunkSpec(seq, 1, total, piece))
    return Plan(specs, [first, total - resumed], interrupt_at=interrupt_at, gap=gap)


def window_plan(total_seconds: float, tables: int, minutes: float) -> tuple[int, float]:
    """How many copies of the material, and how far apart the windows start.

    Ten tables of forty minutes want four hundred minutes; three hours of test
    recordings cover it only by repeating. Repeating is fine — no two tables
    send the same window — but say so, because two tables hearing the same
    conversation shows up in the analysis, not in the protocol.
    """
    window = minutes * 60
    if total_seconds < window:
        # a window longer than the material would loop inside one table's own
        # recording: the same voices saying the same thing twice, which is not
        # audio anybody can read a transcript of
        raise SystemExit(
            f"{total_seconds / 60:.0f} minutes of test audio cannot cover "
            f"a {minutes:g} minute window"
        )
    need = tables * window
    copies = max(1, -(-int(need) // int(total_seconds)))
    if copies > MAX_LOOP_COPIES:
        raise SystemExit(
            f"{total_seconds / 60:.0f} minutes of test audio would have to repeat "
            f"{copies} times for {tables} tables x {minutes:g} minutes; every table "
            f"would hear the same conversation. Record more, or shorten the run."
        )
    stride = (total_seconds * copies - window) / max(1, tables - 1) if tables > 1 else 0.0
    return copies, stride


# ---------------------------------------------------------------------------
# A table
# ---------------------------------------------------------------------------


@dataclass
class Table:
    link: Link
    bearer: str = ""
    number: int = 0
    round_id: str = ""
    recording_id: str = ""
    plan: Plan | None = None
    #: per segment: the cut file and its measured duration
    cuts: list[tuple[pathlib.Path, float]] = field(default_factory=list)
    pieces: list[list[Piece]] = field(default_factory=list)
    queue: queue.Queue[ChunkSpec | None] = field(default_factory=queue.Queue)
    sent: int = 0
    acked: int = 0
    duplicates: int = 0
    max_backlog: int = 0
    interrupted: bool = False
    capture_ok: bool = True
    stop: threading.Event = field(default_factory=threading.Event)
    device_log: list[dict] = field(default_factory=list)
    captions: list[tuple[bool, str]] = field(default_factory=list)
    server: dict = field(default_factory=dict)
    final_state: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def expected_seconds(self) -> float:
        return sum(seconds for _, seconds in self.cuts)

    def all_pieces(self) -> list[Piece]:
        """Every piece in sequence order — the manifest the server should hold."""
        assert self.plan is not None
        ordered: list[Piece] = []
        for spec in sorted(self.plan.specs, key=lambda s: s.seq):
            ordered.append(self.pieces[spec.segment][spec.piece])
        return ordered

    def note(self, message: str) -> None:
        self.notes.append(message)

    def client_log(self, event: str, **data) -> None:
        """A device-log line, in the vocabulary scripts/device-report.py reads,
        so the operator's own tooling can read this run."""
        entry = {"ts": time.time(), "level": "info", "event": event}
        if data:
            entry["data"] = data
        self.device_log.append(entry)


def bytes_of(table: Table, spec: ChunkSpec) -> bytes:
    path, _ = table.cuts[spec.segment]
    piece = table.pieces[spec.segment][spec.piece]
    with path.open("rb") as handle:
        handle.seek(piece.offset)
        return handle.read(piece.length)


# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------


def preflight(links: list[Link], args, metrics: Metrics,
              breaker: Breaker) -> tuple[list[Table], str]:
    """Join, one at a time, and refuse anything that does not add up.

    Sequentially and with no retry on purpose: the public route reports every
    401/403/429 to Nextcloud's brute-force protection against OUR address, so a
    stale set of ten links would earn ten strikes and then throttle everything
    we send, including the real phones behind the same connection at a venue.
    """
    client = Client(links[0].base, metrics, breaker)
    tables: list[Table] = []
    spares = list(links)
    assembly_id = ""
    assembly_name = ""
    handling: dict = {}
    mode = ""
    while spares and len(tables) < args.tables:
        link = spares.pop(0)
        reply = client.call("POST", "/api/v1/public/join", json_body={"token": link.token},
                            endpoint="join")
        if not reply.ok:
            say(f"  table {link.printed_table or '?'}: join refused "
                f"({reply.status or reply.fault} {reply.detail()}) — {mask(link.token)}")
            if reply.status in (401, 403, 404, 410):
                say("  that token is expired or unknown; moving to the next link and NOT retrying")
                continue
            raise SystemExit("join failed in a way that will not improve by repeating it")
        body = reply.body if isinstance(reply.body, dict) else {}
        assembly = body.get("assembly") or {}
        if not assembly_id:
            assembly_id = assembly.get("id", "")
            handling = body.get("data_handling") or {}
            mode = assembly.get("recording_mode", "")
            name = assembly_name = assembly.get("name", "")
            if not re.search(args.expect_name, name):
                raise SystemExit(
                    f"the assembly is called {name!r}, which does not match "
                    f"{args.expect_name!r}. This run would inject "
                    f"{args.tables * args.minutes:g} table-minutes of our audio into it. "
                    f"Pass --expect-name '' only if you are certain."
                )
            say(f"  assembly: {name}  ({mode}, {assembly.get('language')})  id {assembly_id[:8]}")
            say(f"  their speech-to-text: {handling.get('stt_provider') or 'none'}"
                f"{' (hosted)' if handling.get('stt_hosted') else ''}"
                f", analysis {'on' if handling.get('analysis_enabled') else 'off'}"
                f", audio kept {handling.get('audio_retention_days')} day(s)")
        elif assembly.get("id") != assembly_id:
            raise SystemExit("the links belong to different assemblies")
        if mode == "plenary" and not args.allow_plenary:
            raise SystemExit("this is a plenary assembly: many phones share one table. "
                             "Pass --allow-plenary if that is really what you want.")
        number = int(body.get("table_number") or 0)
        if any(table.number == number for table in tables):
            say(f"  table {number} answered twice; skipping the duplicate")
            continue
        rounds = body.get("rounds") or []
        target = next((r for r in rounds if r.get("status") == "ACTIVE"), None) or (
            rounds[0] if rounds else None)
        if target is None:
            raise SystemExit("the assembly has no rounds")
        if target.get("recorded_state") and not args.allow_recorded:
            raise SystemExit(
                f"table {number} has already recorded round {target.get('position')} "
                f"(state {target['recorded_state']}). Use fresh tables or --allow-recorded."
            )
        table = Table(link=link, bearer=body["session_token"], number=number,
                      round_id=target["id"])
        tables.append(table)
    if len(tables) < args.tables:
        raise SystemExit(f"only {len(tables)} of {args.tables} tables could join")
    client.close()
    return tables, assembly_name


def wait_for_active(table: Table, metrics: Metrics, breaker: Breaker,
                    minutes_cap: float, stop: threading.Event) -> bool:
    """Wait for a human to press "Start round".

    The organizer API is out of reach for a script (the proxy wants a Nextcloud
    session), so this is the handshake: the facilitator presses the button when
    they are ready and every table notices within five seconds.
    """
    client = Client(table.link.base, metrics, breaker)
    deadline = time.monotonic() + minutes_cap * 60
    announced = 0.0
    try:
        while not stop.is_set() and time.monotonic() < deadline:
            reply = client.call("GET", "/api/v1/public/recorder/status",
                                bearer=table.bearer, endpoint="status")
            body = reply.body if isinstance(reply.body, dict) else {}
            for entry in body.get("rounds") or []:
                if entry.get("id") != table.round_id:
                    continue
                if entry.get("status") == "ACTIVE":
                    return True
                if entry.get("status") not in ("NOT_STARTED",):
                    say(f"  round {entry.get('position')} is {entry.get('status')}, "
                        f"not startable")
                    return False
            if time.monotonic() - announced > 15:
                announced = time.monotonic()
                left = (deadline - time.monotonic()) / 60
                say(f"  [{stamp()}] waiting for the facilitator … {left:.0f} min left")
            stop.wait(5)
        return False
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------


def producer(table: Table, t_zero: float, stop: threading.Event) -> None:
    """Capture: hands chunks to the uploader on an absolute schedule.

    A real phone writes to IndexedDB and keeps capturing whatever the network
    is doing, so a stalled server produces a backlog and then a burst. Uploading
    inline (as load_h does) would quietly stretch the clock instead, and hide
    the very failure this run is looking for.
    """
    assert table.plan is not None
    try:
        for spec in table.plan.specs:
            if stop.is_set() or table.stop.is_set():
                break
            delay = t_zero + spec.due - time.monotonic()
            if delay > 0 and (stop.wait(delay) or table.stop.is_set()):
                break
            # the microphone is back: say so before the first chunk of the new
            # session, which is what the phone's tryResume() logs
            if spec.segment > 0 and not table.capture_ok:
                table.capture_ok = True
                table.client_log("capture_resumed", segment=spec.segment,
                                 interruptedMs=int(table.plan.gap * 1000))
                say(f"  [{stamp()}] table {table.number}: capture resumed, segment "
                    f"{spec.segment}")
            table.queue.put(spec)
            table.max_backlog = max(table.max_backlog, table.queue.qsize())
            piece = table.pieces[spec.segment][spec.piece]
            table.client_log("chunk_saved_local", seq=spec.seq, bytes=piece.length,
                             segment=spec.segment)
            # the screen just went off: the flush chunk of the dead session has
            # been queued and nothing follows for the length of the gap
            if table.plan.gap and spec.segment == 0 and spec.due >= table.plan.interrupt_at:
                table.interrupted = True
                table.capture_ok = False
                table.client_log("capture_interrupted", cause="track_muted", segment=0,
                                 seq=spec.seq)
                say(f"  [{stamp()}] table {table.number}: capture interrupted for "
                    f"{table.plan.gap:.0f}s")
    finally:
        table.queue.put(None)


def uploader(table: Table, stop: threading.Event, metrics: Metrics, breaker: Breaker) -> None:
    """Upload in order, retrying like the engine does.

    A real phone never gives up on a stored chunk; it retries with a doubling
    delay until the page closes. A 4xx that is not 429 is different: it will
    not become true by repeating, and continuing past it would leave a gap,
    which makes everything after it undecodable — so the table stops there and
    completes with the contiguous prefix, the salvage the app already models.
    """
    client = Client(table.link.base, metrics, breaker)
    delay = RETRY_BASE_SECONDS
    try:
        while True:
            spec = table.queue.get()
            if spec is None:
                return
            blob = bytes_of(table, spec)
            headers = {
                "X-Chunk-SHA256": table.pieces[spec.segment][spec.piece].sha256,
                "X-Chunk-Segment": str(spec.segment),
            }
            while not stop.is_set():
                reply = client.call(
                    "POST",
                    f"/api/v1/public/recorder/recordings/{table.recording_id}"
                    f"/chunks/{spec.seq}",
                    raw=blob, headers=headers, bearer=table.bearer, endpoint="chunk",
                    timeout=120,
                )
                if reply.ok:
                    table.sent = max(table.sent, spec.seq + 1)
                    table.acked += 1
                    if isinstance(reply.body, dict) and reply.body.get("duplicate"):
                        table.duplicates += 1
                    table.client_log("chunk_acked", seq=spec.seq)
                    delay = RETRY_BASE_SECONDS
                    break
                if 400 <= reply.status < 500 and reply.status != 429:
                    table.note(f"chunk {spec.seq} refused: {reply.status} {reply.detail()}")
                    table.stop.set()
                    return
                table.client_log("chunk_upload_failed", seq=spec.seq,
                                 error=f"{reply.status or reply.fault}")
                if stop.wait(delay):
                    return
                delay = min(delay * 2, RETRY_MAX_SECONDS)
    finally:
        client.close()


def monitor(table: Table, stop: threading.Event, metrics: Metrics, breaker: Breaker) -> None:
    """Everything a phone says while it records, on its own schedules."""
    client = Client(table.link.base, metrics, breaker)
    next_beat = next_status = next_live = next_logs = time.monotonic()
    try:
        while not stop.is_set() and not table.stop.is_set():
            now = time.monotonic()
            if now >= next_beat:
                next_beat = now + HEARTBEAT_SECONDS
                client.call("POST", "/api/v1/public/recorder/heartbeat", json_body={
                    "recording_id": table.recording_id,
                    "recording_active": True,
                    "armed": False,
                    "local_chunks": table.sent,
                    "acked_chunks": table.acked,
                    "storage_ok": True,
                    "storage_free_mb": 4096.0,
                    "local_recordings": 1,
                    "battery_level": 0.85,
                    "visible": table.capture_ok,
                    "capture_ok": table.capture_ok,
                    "screen_awake": True,
                }, bearer=table.bearer, endpoint="heartbeat", timeout=30)
            if now >= next_status:
                next_status = now + STATUS_POLL_SECONDS
                reply = client.call("GET", "/api/v1/public/recorder/status",
                                    bearer=table.bearer, endpoint="status", timeout=45)
                body = reply.body if isinstance(reply.body, dict) else {}
                if body.get("assembly_closed"):
                    table.note("the organizer closed the assembly mid-round")
                    table.stop.set()
                for entry in body.get("rounds") or []:
                    if entry.get("id") == table.round_id and entry.get("status") != "ACTIVE":
                        table.note(f"the facilitator ended the round ({entry.get('status')})")
                        table.stop.set()
            if now >= next_live:
                next_live = now + LIVE_POLL_SECONDS
                reply = client.call(
                    "GET",
                    f"/api/v1/public/recorder/recordings/{table.recording_id}/live",
                    bearer=table.bearer, endpoint="live", timeout=45)
                body = reply.body if isinstance(reply.body, dict) else {}
                table.captions.append((bool(body.get("lines")), str(body.get("reason", ""))))
            if now >= next_logs:
                next_logs = now + LOG_SHIP_SECONDS
                ship_logs(table, client)
            stop.wait(0.5)
    finally:
        ship_logs(table, client)
        client.close()


def ship_logs(table: Table, client: Client) -> None:
    if not table.device_log:
        return
    batch, table.device_log = table.device_log[:MAX_LOG_ENTRIES], table.device_log[MAX_LOG_ENTRIES:]
    client.call("POST", "/api/v1/public/recorder/logs", json_body={"entries": batch},
                bearer=table.bearer, endpoint="logs", timeout=30)


def run_table(table: Table, barrier: threading.Barrier, t_zero: float,
              stop: threading.Event, metrics: Metrics, breaker: Breaker) -> None:
    client = Client(table.link.base, metrics, breaker)
    try:
        try:
            barrier.wait(timeout=120)
        except threading.BrokenBarrierError:
            return
        reply = client.call("POST", "/api/v1/public/recorder/start", json_body={
            "round_id": table.round_id, "mime_type": "audio/webm;codecs=opus",
        }, bearer=table.bearer, endpoint="start", timeout=60)
        if not reply.ok or not isinstance(reply.body, dict):
            table.note(f"start refused: {reply.status or reply.fault} {reply.detail()}")
            return
        table.recording_id = reply.body["recording_id"]
        # say what this is, in the field device-report.py reads as the browser:
        # an operator looking at their own device logs afterwards should not
        # have to guess which sessions were the load test
        table.client_log("device_info", ua="citizens-load-i (virtual table, not a phone)",
                         standalone=False, online=True)
        table.client_log("recording_started", recordingId=table.recording_id,
                         mimeType="audio/webm;codecs=opus")
        table.client_log("wake_lock_acquired")
        threads = [
            threading.Thread(target=producer, args=(table, t_zero, stop),
                             name=f"produce-{table.number}"),
            threading.Thread(target=uploader, args=(table, stop, metrics, breaker),
                             name=f"upload-{table.number}"),
            threading.Thread(target=monitor, args=(table, stop, metrics, breaker),
                             name=f"monitor-{table.number}"),
        ]
        for thread in threads:
            thread.start()
        threads[0].join()  # capture finished (or was stopped)
        table.queue.put(None)
        threads[1].join(timeout=300)  # let the backlog drain
        table.stop.set()
        threads[2].join(timeout=30)
        finish(table, client, stop)
    finally:
        client.close()


def finish(table: Table, client: Client, stop: threading.Event) -> None:
    """Declare the recording complete, then watch the server verify it.

    The contiguous prefix, never more: declaring chunks the server does not
    have would ask it to assemble across a gap, and audio.py truncates to the
    declared total rather than guessing.
    """
    table.client_log("finish_requested")
    ship_logs(table, client)
    if not table.sent:
        table.note("nothing was uploaded")
        return
    reply = client.call(
        "POST", f"/api/v1/public/recorder/recordings/{table.recording_id}/complete",
        json_body={"total_chunks": table.sent}, bearer=table.bearer, endpoint="complete",
        timeout=120)
    if not reply.ok:
        table.note(f"complete refused: {reply.status or reply.fault} {reply.detail()}")
        return
    body = reply.body if isinstance(reply.body, dict) else {}
    if body.get("missing_sequences"):
        table.note(f"the server is missing chunks {body['missing_sequences'][:6]}")
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline and not stop.is_set():
        status = client.call(
            "GET", f"/api/v1/public/recorder/recordings/{table.recording_id}",
            bearer=table.bearer, endpoint="recording", timeout=60)
        if status.ok and isinstance(status.body, dict):
            table.server = status.body
            table.final_state = str(status.body.get("state", ""))
            if table.final_state in COMPLETED_STATES or table.final_state in (
                    "AUDIO_INVALID", "UPLOAD_INCOMPLETE"):
                return
        time.sleep(SYNC_POLL_SECONDS)


def wait_for_processing(tables: list[Table], minutes: float, stop: threading.Event,
                        metrics: Metrics, breaker: Breaker) -> None:
    """The tail: transcription, then analysis, watched from a phone's seat.

    On the read-only status route, not the per-recording one — that one runs on
    a write session, and ten of them polling while ten assemblies run is the
    busiest the writer slot ever gets.
    """
    if minutes <= 0 or not tables:
        return
    clients = {table.number: Client(table.link.base, metrics, breaker) for table in tables}
    deadline = time.monotonic() + minutes * 60
    say(f"\nwaiting up to {minutes:.0f} min for transcription and analysis…")
    try:
        while time.monotonic() < deadline and not stop.is_set():
            states: dict[str, int] = {}
            summaries = 0
            for table in tables:
                reply = clients[table.number].call(
                    "GET", "/api/v1/public/recorder/status", bearer=table.bearer,
                    endpoint="status", timeout=60)
                body = reply.body if isinstance(reply.body, dict) else {}
                for entry in body.get("rounds") or []:
                    if entry.get("id") != table.round_id:
                        continue
                    state = entry.get("recorded_state") or "?"
                    table.final_state = state
                    states[state] = states.get(state, 0) + 1
                    if entry.get("table_summary"):
                        summaries += 1
            say(f"    [{stamp()}] " + "  ".join(f"{k}={v}" for k, v in sorted(states.items()))
                + f"  summaries={summaries}/{len(tables)}")
            settled = sum(count for state, count in states.items()
                          if state in ("READY_FOR_REVIEW", "REVIEWED", "TRANSCRIPTION_FAILED",
                                       "ANALYSIS_FAILED", "AUDIO_INVALID"))
            if settled == len(tables):
                return
            stop.wait(30)
    finally:
        for client in clients.values():
            client.close()


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def render(run: dict) -> str:
    lines: list[str] = ["", "=" * 74]
    lines.append(f"target       : {run['base']}")
    lines.append(f"declares     : Citizens {run['version'] or 'unknown'}")
    lines.append(f"from         : {run['our_ip']}")
    lines.append(f"assembly     : {run['assembly']}")
    lines.append(f"tables       : {run['tables']} x {run['minutes']:g} min"
                 f"   interrupted: {run['interrupted'] or 'none'}")
    lines.append(f"audio        : {run['audio']}")
    lines.append(f"started      : {run['started_utc']} UTC   elapsed "
                 f"{run['elapsed'] / 60:.1f} min")
    if run.get("aborted"):
        lines.append(f"ABORTED      : {run['aborted']}")

    lines.append("\n-- per table " + "-" * 60)
    lines.append("  tbl  chunks   MB   seg  state             server s  expected s  manifest")
    for entry in run["per_table"]:
        lines.append(
            f"  {entry['number']:>3}  {entry['sent']:>3}/{entry['planned']:<3} "
            f"{entry['megabytes']:>5.1f} {entry['segments']:>4}  "
            f"{entry['state'][:17]:<17} {entry['server_seconds'] or 0:>8.1f}  "
            f"{entry['expected_seconds']:>10.1f}  {entry['manifest']}"
        )
        for note in entry["notes"]:
            lines.append(f"       ! {note}")

    lines.append("\n-- requests " + "-" * 61)
    for endpoint, counts in sorted(run["outcomes"].items()):
        p50, p95, worst = run["latency"][endpoint]
        total = sum(counts.values())
        detail = " ".join(f"{name}={count}" for name, count in sorted(counts.items())
                          if name != "ok")
        lines.append(f"  {endpoint:<10} n={total:<5} median={p50 * 1000:>6.0f}ms "
                     f"p95={p95 * 1000:>7.0f}ms max={worst * 1000:>8.0f}ms  {detail}")
    if run["worst_minute"]:
        minute, bucket = run["worst_minute"]
        lines.append(f"  worst minute: +{minute} min, {bucket.get('n', 0)} requests, "
                     f"slowest {bucket.get('worst', 0):.1f}s")
    if run["faults"]:
        lines.append("\n-- every server error, dropped connection and timeout " + "-" * 20)
        for when, endpoint, outcome, detail in run["faults"][:40]:
            lines.append(f"  {when} {endpoint:<10} {outcome:<12} {detail[:80]}")
        if len(run["faults"]) > 40:
            lines.append(f"  … and {len(run['faults']) - 40} more")

    lines.append("\n-- live captions " + "-" * 56)
    for entry in run["per_table"]:
        polls = entry["captions"]
        if not polls:
            continue
        with_text = sum(1 for has, _ in polls if has)
        reasons = sorted({reason for _, reason in polls if reason})
        lines.append(f"  table {entry['number']:>3}: {with_text:>3}/{len(polls):<3} polls "
                     f"carried text ({100 * with_text / len(polls):5.1f}%)"
                     + (f"  reasons={reasons}" if reasons else ""))

    if run["interrupted"]:
        lines.append("\n-- the interrupted tables " + "-" * 47)
        for entry in run["per_table"]:
            if entry["segments"] < 2:
                continue
            drift = (entry["server_seconds"] or 0) - entry["expected_seconds"]
            verdict = "SEGMENTS JOINED" if abs(drift) <= 2.5 else "NOT JOINED CORRECTLY"
            lines.append(
                f"  table {entry['number']:>3}: gap {run['gap']:.0f}s, "
                f"expected {entry['expected_seconds']:.1f}s, server says "
                f"{entry['server_seconds'] or 0:.1f}s ({drift:+.1f}s) -> {verdict}"
            )

    ok, reasons = verdict_of(run)
    lines.append("\n-- verdict " + "-" * 62)
    for reason in reasons:
        lines.append(f"  {reason}")
    lines.append("\n" + ("PASS" if ok else "FAIL"))
    lines.append("\nask the operators for, while it is fresh:")
    lines.append("  docker logs nc_app_citizens --since 30m 2>&1 | "
                 "grep -E 'QueuePool|database is locked|db_pool_wait|sweep_failed|"
                 "chunk_segment_started|audio_segments_joined'")
    lines.append("  grep -c AH00161 /var/log/apache2/error.log   # PHP workers exhausted")
    lines.append("  sh scripts/event-status.sh | grep -E 'db pool|oom_killed'")
    lines.append(f"  python3 scripts/device-report.py --assembly '{run['assembly'][:24]}'")
    lines.append("\nand when you are done, ask them to delete the test assembly: "
                 "it removes the audio.")
    return "\n".join(lines)


def verdict_of(run: dict) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    ok = True
    if run.get("aborted"):
        ok = False
        reasons.append(f"the run was stopped early: {run['aborted']}")
    for entry in run["per_table"]:
        if entry["state"] not in COMPLETED_STATES:
            ok = False
            reasons.append(f"table {entry['number']} ended in {entry['state'] or 'no state'}")
        if entry["manifest"] == "MISMATCH":
            ok = False
            reasons.append(f"table {entry['number']}: the server holds different bytes")
        server = entry["server_seconds"] or 0
        if server and abs(server - entry["expected_seconds"]) > 2.5:
            ok = False
            reasons.append(
                f"table {entry['number']}: {server:.1f}s of audio against "
                f"{entry['expected_seconds']:.1f}s uploaded"
            )
    server_errors = sum(
        count for counts in run["outcomes"].values()
        for name, count in counts.items()
        if name in ("5xx", "timeout", "conn_reset", "conn_closed")
    )
    if server_errors:
        ok = False
        reasons.append(f"{server_errors} requests failed on the server's side")
    if ok:
        reasons.append("every table's audio arrived, byte for byte, and nothing failed")
    return ok, reasons


def build_run(args, tables: list[Table], metrics: Metrics, started_utc: str,
              elapsed: float, version: str, assembly: str, audio: str,
              our_ip: str, aborted: str) -> dict:
    per_table = []
    for table in tables:
        pieces = table.all_pieces() if table.plan else []
        expected_sha, expected_bytes = manifest_of(pieces[:table.sent]) if pieces else ("", 0)
        server_sha = str(table.server.get("audio_manifest_sha256") or "")
        if not server_sha:
            manifest = "unknown"
        elif server_sha == expected_sha and table.server.get(
                "audio_manifest_bytes") == expected_bytes:
            manifest = "match"
        else:
            manifest = "MISMATCH"
        per_table.append({
            "number": table.number,
            "sent": table.sent,
            "planned": len(table.plan.specs) if table.plan else 0,
            "megabytes": expected_bytes / 1e6,
            "segments": table.plan.segments if table.plan else 0,
            "state": table.final_state,
            "server_seconds": table.server.get("duration_seconds"),
            "expected_seconds": table.expected_seconds,
            "manifest": manifest,
            "captions": table.captions,
            "notes": table.notes,
            "recording_id": table.recording_id,
            "duplicates": table.duplicates,
            "max_backlog": table.max_backlog,
        })
    worst = max(metrics.minutes.items(), key=lambda kv: kv[1].get("worst", 0),
                default=None)
    return {
        "base": tables[0].link.base if tables else "",
        "version": version,
        "our_ip": our_ip,
        "assembly": assembly,
        "tables": len(tables),
        "minutes": args.minutes,
        "interrupted": [t.number for t in tables if t.plan and t.plan.segments > 1],
        "gap": args.interrupt_seconds,
        "audio": audio,
        "started_utc": started_utc,
        "elapsed": elapsed,
        "aborted": aborted,
        "per_table": per_table,
        "outcomes": metrics.outcomes,
        "latency": {name: metrics.percentiles(name) for name in metrics.outcomes},
        "worst_minute": worst,
        "faults": metrics.faults,
    }


# ---------------------------------------------------------------------------
# Seeding a throwaway assembly on THIS host, to prove the script
# ---------------------------------------------------------------------------


def local_appapi(container: str, repo: pathlib.Path) -> tuple[str, dict]:
    """The organizer API on this host — the one thing the remote path never needs.

    Lifted from load_h_realtime_assembly.py:91-130: the container's address on
    the docker network plus AppAPI's shared-secret triple. A remote instance
    needs none of it, which is the whole point of this script; seeding a test
    assembly here does.
    """
    ip = subprocess.run(
        ["docker", "inspect", "-f",
         "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}", container],
        capture_output=True, text=True, check=True, timeout=60,
    ).stdout.split()[0]
    secret_file = repo / ".app_secret"
    secret = secret_file.read_text().strip() if secret_file.exists() else ""
    if not secret:
        env = subprocess.run(
            ["docker", "inspect", "-f", "{{range .Config.Env}}{{println .}}{{end}}", container],
            capture_output=True, text=True, check=True, timeout=60).stdout
        secret = next((line.split("=", 1)[1] for line in env.splitlines()
                       if line.startswith("APP_SECRET=")), "")
    if not secret:
        raise SystemExit("no .app_secret and no APP_SECRET in the container")
    user = os.environ.get("CITIZENS_ORGANIZER", "alex")
    return f"http://{ip}:23000", {
        "EX-APP-ID": "citizens",
        "EX-APP-VERSION": "1.0.0",
        "AUTHORIZATION-APP-API": base64.b64encode(f"{user}:{secret}".encode()).decode(),
    }


def seed_local(args, metrics: Metrics) -> list[Link]:
    base, headers = local_appapi(args.container, pathlib.Path(args.repo))
    client = Client(base, metrics)
    stamp_name = time.strftime("%Y-%m-%d %H:%M")
    reply = client.call("POST", "/api/v1/assemblies", json_body={
        "name": f"TEST Carico remoto {stamp_name}",
        "language": "it",
        "recording_mode": "orchestrated",
        "default_table_count": args.tables,
        "rounds": [{"title": "Prova di carico", "question": "Prova?",
                    "duration_minutes": max(1, int(args.minutes) + 2)}],
    }, headers=headers, endpoint="seed")
    if not reply.ok or not isinstance(reply.body, dict):
        raise SystemExit(f"could not create the local assembly: {reply.status} {reply.detail()}")
    assembly = reply.body
    round_id = assembly["rounds"][0]["id"]
    links = [parse_link(invite["url"], printed_table=invite.get("table_number"))
             for invite in assembly["invites"]]
    say(f"  seeded {assembly['name']}  ({assembly['id']})  {len(links)} tables")
    say(f"  delete it afterwards: curl -X DELETE -H 'EX-APP-ID: citizens' "
        f"-H 'EX-APP-VERSION: 1.0.0' -H \"AUTHORIZATION-APP-API: "
        f"$(printf '{os.environ.get('CITIZENS_ORGANIZER', 'alex')}:%s' "
        f"\"$(cat {args.repo}/.app_secret)\" | base64 -w0)\" "
        f"{base}/api/v1/assemblies/{assembly['id']}")
    args._local = (client, headers, round_id, assembly)
    return links


def local_facilitator(args, action: str) -> None:
    if not getattr(args, "_local", None):
        return
    client, headers, round_id, _ = args._local
    client.call("POST", f"/api/v1/rounds/{round_id}/{action}", json_body={},
                headers=headers, endpoint="seed")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def public_ip() -> str:
    """Our address, so the operators can tell this run from their own phones —
    and from an attack, given the public route reports failures to their
    brute-force protection."""
    try:
        with urllib.request.urlopen("https://ifconfig.me", timeout=8) as response:
            return response.read().decode().strip()[:45]
    except Exception:
        return "unknown"


def prepare_audio(args, tables: list[Table], workdir: pathlib.Path) -> str:
    """Give every table its own window, and its chunk receipts."""
    interrupt_at = round(args.minutes * 60 * 0.4) + 3  # off the ten-second grid
    plans = []
    for index in range(len(tables)):
        interrupted = index < args.interrupt
        plans.append(plan_chunks(
            args.minutes,
            interrupt_at=interrupt_at if interrupted else 0.0,
            gap=args.interrupt_seconds if interrupted else 0.0,
        ))

    if args.tone:
        for table, plan in zip(tables, plans, strict=True):
            table.plan = plan
            table.cuts = []
            table.pieces = []
            for segment, seconds in enumerate(plan.segment_seconds):
                path = tone_file(workdir, seconds, table.number * 2 + segment)
                measured = ffprobe_seconds(path)
                table.cuts.append((path, measured))
                table.pieces.append(slice_pieces(path, plan.pieces_in(segment)))
            say(f"    table {table.number:>3}: {len(plan.specs):>3} chunks, "
                f"{plan.segments} segment(s), {table.expected_seconds:.0f}s of tone")
        return f"a sine tone, {args.minutes:g} min per table (no speech, no transcript)"

    sources = source_recordings(args.container, args.audio_pattern)
    if not sources:
        raise SystemExit(
            f"no recordings matching {args.audio_pattern!r} in {args.container}. "
            f"Use --tone, or --audio-pattern to widen it — but never point it at "
            f"real citizens' assemblies."
        )
    say(f"  {len(sources)} candidate recordings; levelling them (one pass, cached)…")
    parts, silent = prepare_parts(sources, args.container, workdir)
    for part in parts:
        say(f"    {part.seconds / 60:5.1f} min  {part.mean_db:6.1f} dB  {part.assembly}")
    for part in silent:
        say(f"    {part.seconds / 60:5.1f} min  {part.mean_db:6.1f} dB  {part.assembly}"
            f"   DROPPED: no audible speech")
    if not parts:
        raise SystemExit("every candidate recording is silent")
    total = sum(part.seconds for part in parts)
    # the window plan has to see the minutes that SURVIVED the drop, or a
    # discarded recording's minutes end up in somebody's window as silence
    copies, stride = window_plan(total, len(tables), args.minutes)
    loop, loop_seconds = concat_loop(parts, workdir, copies)
    say(f"  material: {loop_seconds / 60:.0f} min ({copies} copy/copies of "
        f"{total / 60:.0f} min), windows {stride / 60:.1f} min apart")
    for index, (table, plan) in enumerate(zip(tables, plans, strict=True)):
        offset = index * stride
        table.plan = plan
        table.cuts = []
        table.pieces = []
        for segment, seconds in enumerate(plan.segment_seconds):
            begin = offset + (0.0 if segment == 0 else plan.interrupt_at + plan.gap)
            path, measured = cut_window(loop, begin, seconds,
                                        cut_name(workdir, loop, begin, seconds))
            table.cuts.append((path, measured))
            table.pieces.append(slice_pieces(path, plan.pieces_in(segment)))
        megabytes = sum(piece.length for pieces in table.pieces for piece in pieces) / 1e6
        say(f"    table {table.number:>3}: {len(plan.specs):>3} chunks, "
            f"{megabytes:5.1f} MB, {plan.segments} segment(s), "
            f"{table.expected_seconds:.0f}s of audio")
        short_by = args.minutes * 60 - plan.gap - table.expected_seconds
        if short_by > 15:
            # the cut came back far shorter than the round: stale audio, or a
            # window that ran off the end of the material. Either way the run
            # would measure the right request rate over the wrong bytes.
            raise SystemExit(
                f"table {table.number}'s audio is {table.expected_seconds:.0f}s for a "
                f"{args.minutes:g}-minute round: {short_by:.0f}s missing. Clear "
                f"{workdir} and try again."
            )
    note = (f"real Italian speech, levelled to -20 LUFS, {copies} copy/copies of "
            f"{total / 60:.0f} min from {len(parts)} recording(s)")
    if silent:
        note += f"; {len(silent)} silent recording(s) discarded"
    return note


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("links", nargs="*", help="join links")
    parser.add_argument("--links", action="append", default=[], dest="link_files",
                        help="file with one join link per line")
    parser.add_argument("--links-pdf", action="append", default=[], dest="link_pdfs",
                        help="the printed QR sheet")
    parser.add_argument("--tables", type=int, default=10)
    parser.add_argument("--only-tables", default="",
                        help="use just these table numbers from the sheet, e.g. 13,14,15 — "
                             "a warm-up on the spares leaves the real tables unrecorded")
    parser.add_argument("--minutes", type=float, default=8.0)
    parser.add_argument("--interrupt", type=int, default=2,
                        help="how many tables simulate the screen going off")
    parser.add_argument("--interrupt-seconds", type=float, default=45.0)
    parser.add_argument("--tone", action="store_true", help="no speech: a sine tone")
    parser.add_argument("--audio-pattern", default=TEST_ASSEMBLY_PATTERN,
                        help="which assemblies' recordings may be replayed")
    parser.add_argument("--expect-name", default="(?i)test",
                        help="refuse an assembly whose name does not match this")
    parser.add_argument("--allow-recorded", action="store_true")
    parser.add_argument("--allow-plenary", action="store_true")
    parser.add_argument("--allow-old-version", action="store_true",
                        help="run against a build older than 0.6.2 (forces --interrupt 0)")
    parser.add_argument("--before-run", action="store_true",
                        help="the deliberate measurement on an old build: implies "
                             "--allow-old-version, no interruptions, tighter abort")
    parser.add_argument("--wait-start-minutes", type=float, default=30.0)
    parser.add_argument("--tail-minutes", type=float, default=-1.0)
    parser.add_argument("--abort-server-errors", type=int, default=15)
    parser.add_argument("--seed-local", action="store_true",
                        help="create a throwaway assembly on THIS host and use its links")
    parser.add_argument("--manual-facilitator", action="store_true",
                        help="with --seed-local, do not start/end the round ourselves")
    parser.add_argument("--container", default="nc_app_citizens")
    parser.add_argument("--repo", default=str(pathlib.Path(__file__).resolve().parents[2]))
    parser.add_argument("--workdir", default="/tmp/citizens-load-i")
    parser.add_argument("--plan-only", action="store_true", help="arithmetic, then stop")
    parser.add_argument("--prepare-audio-only", action="store_true",
                        help="level, concatenate and cut the audio, then stop — the slow "
                             "part, done while the operators set their assembly up. The "
                             "cuts are named by content, so the real run finds them cached.")
    parser.add_argument("--no-ip-lookup", action="store_true")
    parser.add_argument("--yes", action="store_true", help="required over 10 minutes")
    args = parser.parse_args()

    if args.before_run:
        # What this mode is for: measuring a build that predates the fix, on
        # purpose. It does NOT shorten the run — it used to cap it at eight
        # minutes, which would have turned a deliberate forty-minute
        # measurement into an eight-minute one without saying so, and a flag
        # that quietly changes what you asked for is how the first run on
        # somebody else's server ended up carrying 40% of its audio.
        args.allow_old_version = True
        args.interrupt = 0
        args.abort_server_errors = min(args.abort_server_errors, 8)
        say("--before-run: old build allowed, interruptions off (the old build "
            f"ignores segments), stopping after {args.abort_server_errors} server errors")
    if args.allow_old_version and args.interrupt:
        raise SystemExit(
            "a build older than 0.6.2 ignores X-Chunk-Segment, so an interrupted table's "
            "audio would be spliced across two container headers and come back broken "
            "while looking fine. Use --interrupt 0."
        )
    if args.minutes > 60:
        raise SystemExit("more than an hour per table is not a rehearsal, it is an event")
    if args.interrupt > args.tables:
        raise SystemExit("more interrupted tables than tables")
    if args.interrupt and args.minutes * 60 * 0.4 + args.interrupt_seconds + 60 > args.minutes * 60:
        raise SystemExit("the round is too short for an interruption plus a real resumption")
    if args.interrupt_seconds > MAX_INTERRUPT_SECONDS:
        raise SystemExit(
            f"an interruption over {MAX_INTERRUPT_SECONDS}s makes the server release the "
            f"table (STALLED_DEVICE_SECONDS); that is a device-replacement test"
        )

    if args.plan_only:
        for interrupted in ({True, False} if args.interrupt else {False}):
            plan = plan_chunks(
                args.minutes,
                interrupt_at=(round(args.minutes * 60 * 0.4) + 3) if interrupted else 0.0,
                gap=args.interrupt_seconds if interrupted else 0.0)
            kind = "interrupted" if interrupted else "plain"
            say(f"{kind} table: {len(plan.specs)} chunks, segments "
                f"{[plan.pieces_in(s) for s in range(plan.segments)]}, "
                f"audio {sum(plan.segment_seconds):.0f}s")
            say("  " + " ".join(f"{s.seq}:{s.segment}@{s.due:.0f}" for s in plan.specs))
        return 0

    workdir = pathlib.Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    if args.prepare_audio_only:
        # No links, no server, no joins: the windows depend on (tables, minutes,
        # interruptions) and the files are named by content, so this is exactly
        # what the real run will look for.
        placeholder = Link(base="https://example.invalid/citizens", token="x" * 32)
        say("preparing audio only — no server is contacted\n")
        note = prepare_audio(args, [Table(link=placeholder, number=index + 1)
                                    for index in range(args.tables)], workdir)
        say(f"\nready: {note}\n  cached in {workdir}")
        return 0

    metrics = Metrics()
    breaker = Breaker(args.abort_server_errors, consecutive_slow=5, slow_seconds=30.0)
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: (say("\ninterrupted — draining"), stop.set()))

    links = seed_local(args, metrics) if args.seed_local else read_links(
        args.link_files, args.link_pdfs, args.links)
    if args.only_tables:
        wanted = [int(part) for part in args.only_tables.replace(" ", "").split(",") if part]
        by_number = {link.printed_table: link for link in links if link.printed_table}
        missing = [number for number in wanted if number not in by_number]
        if missing:
            raise SystemExit(f"the sheet has no table {missing}")
        links = [by_number[number] for number in wanted]
        args.tables = min(args.tables, len(links))
    say(f"{len(links)} link(s) for {urllib.parse.urlsplit(links[0].base).netloc}"
        f"  ({args.tables} tables, {max(0, len(links) - args.tables)} spare)")
    if len(links) < args.tables:
        raise SystemExit(f"{args.tables} tables asked for, {len(links)} links given")

    probe = Client(links[0].base, metrics)
    version = deployed_version(probe)
    probe.close()
    numbers = version_tuple(version)
    say(f"the server declares Citizens {version or 'nothing readable'}")
    if numbers is None or numbers < SEGMENT_VERSION:
        if not args.allow_old_version:
            raise SystemExit(
                f"that build is older than {'.'.join(map(str, SEGMENT_VERSION))}, whose "
                f"status poll holds a database connection across six calls to Nextcloud: "
                f"ten tables are expected to exhaust the connection pool and answer the "
                f"phones with 500. Ask them to update first, or pass --before-run to "
                f"measure it deliberately."
            )
        say("  running anyway: this is the deliberate 'before' measurement")

    our_ip = "unknown" if args.no_ip_lookup else public_ip()
    minutes_total = args.tables * args.minutes
    say(f"\nthis run will send {minutes_total:g} table-minutes of audio from {our_ip}")
    if not args.seed_local:
        say(f"  their speech-to-text is billed twice for it, and their disk keeps "
            f"~{minutes_total * 0.35:.0f} MB until the assembly is deleted")
    if args.minutes > 10 and not args.yes:
        raise SystemExit("over ten minutes per table needs --yes (read the line above)")

    say("\njoining…")
    tables, assembly_name = preflight(links, args, metrics, breaker)
    say(f"  {len(tables)} tables joined: {[t.number for t in tables]}")
    say("\npreparing audio…")
    audio_note = prepare_audio(args, tables, workdir)

    if args.seed_local and not args.manual_facilitator:
        local_facilitator(args, "start")
    else:
        say("\n" + "=" * 74)
        say(">>>  ASK THE FACILITATOR TO PRESS \"START ROUND\" NOW  <<<")
        say("=" * 74)
    if not wait_for_active(tables[0], metrics, breaker, args.wait_start_minutes, stop):
        raise SystemExit("the round never became ACTIVE")
    say(f"  [{stamp()}] the round is ACTIVE")

    started_utc = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    began = time.monotonic()
    barrier = threading.Barrier(len(tables))
    t_zero = time.monotonic() + 3
    threads = [threading.Thread(target=run_table,
                                args=(table, barrier, t_zero, stop, metrics, breaker),
                                name=f"table-{table.number}")
               for table in tables]
    for thread in threads:
        thread.start()
    watchdog = threading.Thread(target=_watch_breaker, args=(breaker, stop), daemon=True)
    watchdog.start()
    for thread in threads:
        thread.join()
    aborted = breaker.tripped()
    if args.seed_local and not args.manual_facilitator:
        local_facilitator(args, "end")

    tail = args.tail_minutes if args.tail_minutes >= 0 else max(
        5.0, min(45.0, minutes_total * 0.6))
    if not aborted and not args.tone:
        wait_for_processing(tables, tail, stop, metrics, breaker)

    run = build_run(args, tables, metrics, started_utc, time.monotonic() - began,
                    version, assembly_name or "unknown", audio_note, our_ip, aborted)
    report = render(run)
    say(report)
    (workdir / "report.txt").write_text(report, encoding="utf-8")
    safe = json.loads(json.dumps(run, default=str))
    (workdir / "run.json").write_text(json.dumps(safe, indent=1), encoding="utf-8")
    say(f"\nartifacts: {workdir}/report.txt and run.json")
    return 0 if verdict_of(run)[0] else 1


def _watch_breaker(breaker: Breaker, stop: threading.Event) -> None:
    while not stop.wait(2):
        reason = breaker.tripped()
        if reason:
            say(f"\n!! stopping: {reason}")
            say("!! their server is in trouble; completing what we can and reporting")
            stop.set()
            return


if __name__ == "__main__":
    sys.exit(main())
