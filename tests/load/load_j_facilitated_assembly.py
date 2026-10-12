#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
# ruff: noqa: E501 — a rehearsal script reads best as one check per line
"""The scripted rehearsal of an organized assembly with the AI assistant on.

Five tables, ten registered people each (two refusals, marked as moved),
two or three recorder phones per table joined through Add recorder codes,
one facilitator phone per table, consent required, two sessions of six
minutes, real assembly audio replayed through the real Nextcloud proxy at
the phones' own cadence, the AI assistant at level Normal ticked every
minute, organizer messages and hands, a stall injected at one table, New
seating between the sessions, closing with the synthesis. Asserts the
routing of the assistant's advice (cards on a connected facilitator phone,
banners on the table phones otherwise), the level cap, the pause, the
stall → failover → CAPTURE_SILENT chain, delivery counts, and prints a
timing summary. Exit 1 on any failed check.

Organizer calls are signed at the container (as the organizer UI's are);
phone and facilitator calls go through the proxy (as the phones' do). The
live engine is switched to the local Vosk for the run and restored after,
unless --no-vosk; the assembly is deleted afterwards unless --keep.

    python3 tests/load/load_j_facilitated_assembly.py --smoke      # 2 tables, 90 s
    python3 tests/load/load_j_facilitated_assembly.py --yes        # the full rehearsal
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

CONTAINER = "nc_app_citizens"
REPO = pathlib.Path(__file__).resolve().parents[2]
SECRET_FILE = REPO / ".app_secret"
PROXY = "https://cloud.democracyinnovators.com/index.php/apps/app_api/proxy/citizens"
ORGANIZER = "rehearsal-0.7"
ADMIN = os.environ.get("CITIZENS_ADMIN", "alex")  # admin routes need a Nextcloud admin
CHUNK_SECONDS = 10
WEBM_CLUSTER_ID = b"\x1f\x43\xb6\x75"

BASE = ""
_LOCK = threading.Lock()
_STOP = threading.Event()
TIMINGS: dict[str, list[float]] = {}
FAILURES: list[str] = []
CHECKS: list[str] = []
SAMPLES: list[dict] = []
TICKS: list[dict] = []
BANNERS: dict[int, list[dict]] = {}   # table -> AI banners seen on its phones
CARDS: dict[int, set[str]] = {}       # table -> advice ids seen on its facilitator phone
CAPTION_POLLS: dict[str, list[bool]] = {}


# --------------------------------------------------------------- plumbing


def sh(*args: str, check: bool = True) -> str:
    return subprocess.run(args, capture_output=True, text=True, check=check).stdout.strip()


def discover_base() -> str:
    ip = sh("docker", "inspect", "-f",
            "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}", CONTAINER).split()[0]
    return f"http://{ip}:23000"


def appapi_headers(user: str = ORGANIZER) -> dict:
    if SECRET_FILE.exists():
        secret = SECRET_FILE.read_text().strip()
    else:
        env = sh("docker", "inspect", "-f", "{{range .Config.Env}}{{println .}}{{end}}", CONTAINER)
        secret = next((line.split("=", 1)[1] for line in env.splitlines()
                       if line.startswith("APP_SECRET=")), "")
    return {
        "EX-APP-ID": "citizens", "EX-APP-VERSION": "1.0.0",
        "AUTHORIZATION-APP-API": base64.b64encode(f"{user}:{secret}".encode()).decode(),
    }


def _timed(phase: str, started: float) -> None:
    with _LOCK:
        TIMINGS.setdefault(phase, []).append(time.monotonic() - started)


def _request(url: str, method: str, headers: dict, body: bytes | None, phase: str,
             raw: bool, timeout: int):
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        payload, status = exc.read() or b"", exc.code
    finally:
        _timed(phase, started)
    if raw:
        return status, payload
    try:
        return status, (json.loads(payload) if payload else {})
    except ValueError:
        return status, {"raw": payload[:200].decode(errors="replace")}


def org(method: str, path: str, data=None, raw: bool = False, phase: str = "organizer",
        timeout: int = 120, user: str | None = None):
    headers = appapi_headers(user or ORGANIZER)
    body = None
    if data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data).encode()
    return _request(BASE + path, method, headers, body, phase, raw, timeout)


def phone(method: str, path: str, data=None, token: str | None = None, phase: str = "phone",
          timeout: int = 60):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None
    if data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data).encode()
    return _request(PROXY + path, method, headers, body, phase, False, timeout)


def phone_chunk(recording_id: str, seq: int, blob: bytes, token: str) -> int:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/octet-stream",
        "X-Chunk-SHA256": hashlib.sha256(blob).hexdigest(),
        "X-Chunk-Segment": "0",
    }
    status, _ = _request(
        f"{PROXY}/api/v1/public/recorder/recordings/{recording_id}/chunks/{seq}",
        "POST", headers, blob, "chunk", False, 120,
    )
    return status


def check(label: str, condition: bool, detail: str = "") -> bool:
    line = ("PASS " if condition else "FAIL ") + label + (f"  [{detail}]" if detail else "")
    with _LOCK:
        CHECKS.append(line)
        if not condition:
            FAILURES.append(label + (f": {detail}" if detail else ""))
    print("  " + line)
    return condition


def must(label: str, condition: bool, detail: str = "") -> None:
    if not check(label, condition, detail):
        raise SystemExit(f"cannot continue: {label} {detail}")


def tok(url: str, route: str = "join") -> str:
    return url.rsplit(f"/{route}/", 1)[1]


# ------------------------------------------------------------------ audio


def real_recordings() -> list[tuple[float, str]]:
    listing = sh(
        "docker", "exec", CONTAINER, "sh", "-c",
        'for f in $(find /data/assembled -type f -name "*.webm"); do '
        'd=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f"); echo "$d $f"; done',
    )
    found = []
    for line in listing.splitlines():
        duration, _, path = line.partition(" ")
        try:
            if float(duration) >= 900:
                found.append((float(duration), path))
        except ValueError:
            continue
    found.sort(reverse=True)
    return found


def cluster_offsets(blob: bytes) -> list[int]:
    """Offsets of the real WebM Clusters. The four id bytes can occur inside
    Opus data by chance; a real Cluster is followed by its size (an EBML
    vint) and then the Timecode element (id 0xE7)."""
    offsets = []
    at = blob.find(WEBM_CLUSTER_ID)
    while at >= 0:
        i = at + 4
        if i < len(blob):
            first = blob[i]
            length = next((n for n in range(1, 9) if first & (0x80 >> (n - 1))), 9)
            if length <= 8 and i + length < len(blob) and blob[i + length] == 0xE7:
                offsets.append(at)
        at = blob.find(WEBM_CLUSTER_ID, at + 1)
    return offsets


def cluster_chunks(blob: bytes, duration: float, start_seconds: float, seconds: int) -> list[bytes]:
    """~10 s chunks cut at WebM Cluster boundaries, the first with the
    container header — what a phone's MediaRecorder produces."""
    offsets = cluster_offsets(blob)
    header = blob[: offsets[0]]
    bps = len(blob) / duration
    start = next((i for i, o in enumerate(offsets) if o >= start_seconds * bps), 0)
    chunks: list[bytes] = []
    piece_start, target = offsets[start], offsets[start] + CHUNK_SECONDS * bps
    for o in offsets[start + 1:]:
        if o >= target:
            chunks.append(blob[piece_start:o])
            piece_start, target = o, o + CHUNK_SECONDS * bps
        if len(chunks) >= seconds // CHUNK_SECONDS:
            break
    if not chunks:
        raise SystemExit("the source recording is too short for this run")
    chunks[0] = header + chunks[0]
    return chunks


def prepare_audio(workdir: pathlib.Path, phones: int, sessions: int, seconds: int) -> list[list[list[bytes]]]:
    """[phone][session] -> chunks. Each phone replays a different stretch of
    a real recording so the tables do not all say the same thing."""
    sources = real_recordings()
    if not sources:
        raise SystemExit("no long recordings in /data/assembled to replay")
    workdir.mkdir(parents=True, exist_ok=True)
    blobs = []
    for index, (duration, path) in enumerate(sources[:6]):
        local = workdir / f"source{index}.webm"
        if not local.exists():
            sh("docker", "cp", f"{CONTAINER}:{path}", str(local))
        blobs.append((duration, local.read_bytes()))
    per_phone = []
    for p in range(phones):
        duration, blob = blobs[p % len(blobs)]
        per_session = []
        for s in range(sessions):
            offset = ((p // len(blobs)) * sessions + s) * seconds
            offset = offset % max(1, int(duration - seconds - 30))
            per_session.append(cluster_chunks(blob, duration, offset, seconds))
        per_phone.append(per_session)
    return per_phone


# -------------------------------------------------------------- settings


def preflight(use_vosk: bool) -> str | None:
    status, settings = org("GET", "/api/v1/admin/providers", user=ADMIN)
    must("admin settings readable (set CITIZENS_ADMIN to a Nextcloud admin)", status == 200 and "stt" in settings, str(status))
    fac = settings.get("facilitator") or {}
    must("the AI assistant has a model to call (facilitator.configured)", fac.get("configured") is True,
         json.dumps({k: v for k, v in fac.items() if "key" not in k}))
    stt = settings.get("stt") or {}
    must("live captions enabled", stt.get("live_enabled") is True, json.dumps(stt.get("provider")))
    previous = stt.get("provider")
    if use_vosk and previous != "vosk":
        models = stt.get("vosk_language_models") or {}
        must("Vosk has an Italian model", bool(models.get("it")), json.dumps(models))
        status, _ = org("PUT", "/api/v1/admin/providers", {"stt_provider": "vosk"}, user=ADMIN)
        must("live engine switched to Vosk for the run", status == 200, str(status))
        print(f"  live/final engine: vosk (was {previous}; restored at the end)")
        return previous
    print(f"  live/final engine: {previous}")
    return None


def restore_provider(previous: str | None) -> None:
    if previous:
        status, _ = org("PUT", "/api/v1/admin/providers", {"stt_provider": previous}, user=ADMIN)
        print(f"  live/final engine restored to {previous}: {status}")


# ----------------------------------------------------------- the phones


class Phone:
    def __init__(self, table: int, slot: int, token: str, chunks: list[list[bytes]]):
        self.table, self.slot, self.token, self.chunks = table, slot, token, chunks
        self.recording_id = ""
        self.sent = 0
        self.seen: set[int] = set()
        self.stall: tuple[float, float] | None = None  # (from, to) seconds into the session

    def start(self, round_id: str) -> None:
        status, body = phone("POST", "/api/v1/public/recorder/start",
                             {"round_id": round_id, "mime_type": "audio/webm;codecs=opus"},
                             token=self.token, phase="start")
        if status != 201:
            with _LOCK:
                FAILURES.append(f"table {self.table} slot {self.slot}: start {status} {body}")
            self.recording_id = ""
            return
        self.recording_id = body["recording_id"]
        self.sent = 0

    def run_session(self, session_index: int, t_zero: float) -> None:
        if not self.recording_id:
            return
        chunks = self.chunks[session_index]
        CAPTION_POLLS.setdefault(f"t{self.table}{'ABCD'[self.slot - 1]}", [])
        for seq, blob in enumerate(chunks):
            if _STOP.is_set():
                break
            due = t_zero + seq * CHUNK_SECONDS
            if (delay := due - time.monotonic()) > 0 and _STOP.wait(delay):
                break
            elapsed = seq * CHUNK_SECONDS
            if self.stall and self.stall[0] <= elapsed < self.stall[1]:
                continue  # the phone is asleep: nothing leaves it
            status = phone_chunk(self.recording_id, seq, blob, self.token)
            if status != 200:
                with _LOCK:
                    FAILURES.append(f"table {self.table} slot {self.slot}: chunk {seq} -> {status}")
                break
            self.sent = seq + 1
            if seq % 3 == 0:
                phone("POST", "/api/v1/public/recorder/heartbeat",
                      {"recording_id": self.recording_id, "recording_active": True, "armed": True,
                       "local_chunks": self.sent, "acked_chunks": self.sent, "storage_ok": True,
                       "capture_ok": True, "visible": True},
                      token=self.token, phase="heartbeat", timeout=30)
                self.poll_status()
            if seq % 2 == 1:
                status, live = phone("GET", f"/api/v1/public/recorder/recordings/{self.recording_id}/live",
                                     token=self.token, phase="live", timeout=30)
                with _LOCK:
                    CAPTION_POLLS[f"t{self.table}{'ABCD'[self.slot - 1]}"].append(bool(live.get("lines")))

    def poll_status(self) -> None:
        status, body = phone("GET", "/api/v1/public/recorder/status", token=self.token, phase="status", timeout=30)
        if status != 200:
            return
        for message in body.get("messages") or []:
            if message["id"] in self.seen:
                continue
            self.seen.add(message["id"])
            if message.get("author") == "ai":
                with _LOCK:
                    BANNERS.setdefault(self.table, []).append(
                        {"id": message["id"], "slot": self.slot, "at": time.time()})
            phone("POST", "/api/v1/public/recorder/messages/seen", {"message_id": message["id"]},
                  token=self.token, phase="seen", timeout=30)

    def complete(self) -> dict:
        if not self.recording_id:
            return {}
        status, body = phone("POST", f"/api/v1/public/recorder/recordings/{self.recording_id}/complete",
                             {"total_chunks": self.sent}, token=self.token, phase="complete")
        if status != 200:
            with _LOCK:
                FAILURES.append(f"table {self.table} slot {self.slot}: complete {status} {body}")
        return body


class FacilitatorPhone:
    def __init__(self, table: int, token: str):
        self.table, self.token = table, token
        self.connected = True
        self.sent_one = False
        self.rated: set[str] = set()
        self.recorder_alerts: list[dict] = []

    def tick(self, policy: dict) -> None:
        """One heartbeat + one status read: cards collected, the policy applied."""
        if not self.connected:
            return
        phone("POST", "/api/v1/public/facilitator/heartbeat", token=self.token, phase="fac-heartbeat", timeout=30)
        status, body = phone("GET", "/api/v1/public/facilitator/status", token=self.token, phase="fac-status", timeout=30)
        if status != 200:
            return
        if body.get("recorder_alerts"):
            self.recorder_alerts.append({"at": time.time(), "alerts": body["recorder_alerts"]})
        for card in body.get("advice") or []:
            with _LOCK:
                CARDS.setdefault(self.table, set()).add(card["id"])
            if policy.get("send_first") and not self.sent_one:
                phone("POST", f"/api/v1/public/facilitator/advice/{card['id']}/send", token=self.token, phase="fac-send")
                self.sent_one = True
            elif policy.get("thumbs_down") and card["id"] not in self.rated:
                phone("POST", f"/api/v1/public/facilitator/advice/{card['id']}/feedback",
                      {"helpful": False}, token=self.token, phase="fac-feedback")
                self.rated.add(card["id"])
            else:
                phone("POST", f"/api/v1/public/facilitator/advice/{card['id']}/dismiss", token=self.token, phase="fac-dismiss")

    def leave(self) -> None:
        phone("POST", "/api/v1/public/facilitator/leave", token=self.token, phase="fac-leave")
        self.connected = False


# ------------------------------------------------------------ organizer


def create_assembly(tables: int, sessions: int, minutes: int) -> dict:
    stamp = time.strftime("%Y-%m-%d %H:%M")
    status, body = org("POST", "/api/v1/assemblies", {
        "name": f"PROVA generale {tables} tavoli {stamp}",
        "language": "it",
        "recording_mode": "orchestrated",
        "default_table_count": tables,
        "participant_consent": "required",
        "ai_facilitator": "normal",
        "rounds": [
            {"title": f"Sessione {i + 1}", "question": q, "objective": o, "duration_minutes": minutes}
            for i, (q, o) in enumerate([
                ("Cosa non funziona nella mobilità del quartiere?", "Tre problemi concreti"),
                ("Cosa proponiamo per i prossimi dodici mesi?", "Tre proposte realizzabili"),
            ][:sessions])
        ],
    })
    must("assembly created (consent required, AI assistant normal)", status == 201
         and body.get("participant_consent") == "required" and body.get("ai_facilitator") == "normal",
         json.dumps(body)[:200])
    return body


def register_people(table_phone: Phone, table: int, people: int, refuse_one: bool) -> None:
    status, notice = phone("GET", "/api/v1/public/recorder/consent-notice", token=table_phone.token, phase="notice")
    must(f"table {table}: notice 2026-10.3", status == 200 and notice.get("version") == "2026-10.3", str(status))
    refuser = None
    for k in range(people):
        yes = not (refuse_one and k == 0)
        act = {
            "name": f"T{table} Persona {k + 1}", "notice_hash": notice["hash"], "notice_read": True,
            "recording_consent": yes, "transcription_consent": yes, "analysis_consent": yes,
            "publication_consent": yes,
        }
        for _attempt in range(6):
            status, body = phone("POST", "/api/v1/public/recorder/participants", act,
                                 token=table_phone.token, phase="register")
            if status == 429:
                time.sleep(10)
                continue
            break
        if status != 201:
            check(f"table {table}: person {k + 1} registered", False, f"{status} {body}")
            continue
        if not yes:
            refuser = body["participant"]["id"]
    if refuse_one:
        status, state = phone("POST", "/api/v1/public/recorder/start",
                              {"round_id": "unused", "mime_type": "audio/webm"}, token=table_phone.token)
        # the real check: the table's consent state says it is blocked by the refusal
        status, roster = phone("GET", "/api/v1/public/recorder/consent-notice", token=table_phone.token)
        refusing = sum(1 for p in roster.get("participants", []) if p.get("refused"))
        check(f"table {table}: one refusal is seated and blocks", refusing == 1, str(refusing))
        status, moved = phone("POST", f"/api/v1/public/recorder/participants/{refuser}/moved",
                              token=table_phone.token, phase="moved")
        check(f"table {table}: the refuser is marked as moved, the table may record",
              status == 200 and moved.get("table", {}).get("can_record") is True
              and moved["table"].get("refusing") == 0, json.dumps(moved.get("table")))


def facilitator_tick() -> int:
    started = time.monotonic()
    status, body = org("POST", "/api/v1/admin/facilitator/tick", {}, phase="tick", timeout=300, user=ADMIN)
    took = time.monotonic() - started
    delivered = body.get("delivered", 0) if status == 200 else -1
    with _LOCK:
        TICKS.append({"at": time.strftime("%H:%M:%S"), "seconds": took, "delivered": delivered, "status": status})
    print(f"    [{time.strftime('%H:%M:%S')}] tick {took:5.1f}s delivered={delivered}")
    return delivered


def sample(round_id: str, label: str) -> dict:
    status, health = org("GET", "/health", phase="health", timeout=30)
    entry = {"t": time.strftime("%H:%M:%S"), "label": label}
    pool = (health or {}).get("pool") or {}
    entry["pool_in_use"] = pool.get("in_use")
    entry["pool_max_wait_ms"] = pool.get("max_wait_ms")
    entry["pool_slow_waits"] = pool.get("slow_waits")
    status, monitor = org("GET", f"/api/v1/rounds/{round_id}/monitor", phase="monitor", timeout=60)
    if status == 200:
        entry["tables"] = {
            t["number"]: {
                "readiness": (t.get("readiness") or {}).get("status"),
                "reasons": [r["code"] for r in (t.get("readiness") or {}).get("reasons", [])],
                "live_source_slot": t.get("live_source_slot"),
                "coverage": {r["slot"]: ((r.get("recording") or {}).get("coverage") or {}).get("percent")
                             for r in t.get("recorders") or []},
            }
            for t in monitor.get("tables", [])
        }
    with _LOCK:
        SAMPLES.append(entry)
    return entry


# ------------------------------------------------------------------ run


def run(tables: int, phones_per_table: list[int], people: int, sessions: int, minutes: int,
        workdir: pathlib.Path, keep: bool, use_vosk: bool) -> int:
    seconds = minutes * 60
    total_phones = sum(phones_per_table)
    print(f"preparing real audio for {total_phones} phones × {sessions} sessions × {minutes} min…")
    audio = prepare_audio(workdir, total_phones, sessions, seconds)

    previous_provider = preflight(use_vosk)
    assembly = None
    try:
        assembly = create_assembly(tables, sessions, minutes)
        aid = assembly["id"]
        rounds = assembly["rounds"]
        invites = {inv["table_number"]: inv["url"] for inv in assembly["invites"]}

        # phones: the table's own, then the extra recorders through its codes
        phones: list[Phone] = []
        facilitators: dict[int, FacilitatorPhone] = {}
        audio_index = 0
        for table in range(1, tables + 1):
            status, joined = phone("POST", "/api/v1/public/join", {"token": tok(invites[table])}, phase="join")
            must(f"table {table}: phone A joins", status == 200, str(status))
            lead = Phone(table, 1, joined["session_token"], audio[audio_index])
            audio_index += 1
            phones.append(lead)
            for extra in range(phones_per_table[table - 1] - 1):
                status, card = phone("POST", "/api/v1/public/recorder/capabilities",
                                     {"purpose": "ADD_RECORDER_TO_TABLE"}, token=lead.token, phase="capability")
                must(f"table {table}: Add recorder code", status == 201, str(status))
                status, joined = phone("POST", "/api/v1/public/join", {"token": tok(card["url"])}, phase="join")
                must(f"table {table}: recorder {'ABCD'[extra + 1]} joins", status == 200
                     and joined.get("joined", {}).get("slot") == extra + 2, json.dumps(joined.get("joined")))
                phones.append(Phone(table, extra + 2, joined["session_token"], audio[audio_index]))
                audio_index += 1
            status, fcard = phone("POST", "/api/v1/public/recorder/capabilities",
                                  {"purpose": "FACILITATE_TABLE"}, token=lead.token, phase="capability")
            must(f"table {table}: facilitator code", status == 201, str(status))
            status, fj = phone("POST", "/api/v1/public/facilitate", {"token": tok(fcard["url"], "facilitate")}, phase="facilitate")
            must(f"table {table}: facilitator phone joins", status == 200 and fj.get("table_number") == table, str(status))
            facilitators[table] = FacilitatorPhone(table, fj["facilitator_token"])
            register_people(lead, table, people, refuse_one=table in (1, 2))
        print(f"  {len(phones)} recorder phones, {len(facilitators)} facilitator phones, "
              f"{tables * people} people registered")

        status, monitor = org("GET", f"/api/v1/rounds/{rounds[0]['id']}/monitor")
        blocked_by_consent = [t["number"] for t in monitor.get("tables", [])
                              if any(r["code"].startswith("PARTICIPANT_") for r in (t.get("readiness") or {}).get("reasons", []))]
        check("no table blocked by consent before the first session", blocked_by_consent == [], str(blocked_by_consent))

        # the policies per table for the assistant's cards
        policies = {t: {} for t in range(1, tables + 1)}
        policies[1] = {"send_first": True}
        if tables >= 4:
            policies[4] = {"thumbs_down": True}
        paused_table = 2 if tables >= 2 else None
        paused_at: float | None = None
        left_table = 3 if tables >= 3 else None
        interventions_by_session: dict[str, list[dict]] = {}

        for s, round_ in enumerate(rounds):
            rid = round_["id"]
            print(f"\n== session {s + 1}: {round_['title']} ({minutes} min) ==")
            if s == 1 and left_table and left_table in facilitators:
                facilitators[left_table].leave()
                print(f"  table {left_table}'s facilitator phone left: its advice goes to the table phones")
            # phone A of table 1 falls silent for two minutes in session 1
            for p in phones:
                p.stall = (90.0, 210.0) if (s == 0 and p.table == 1 and p.slot == 1 and seconds >= 240) else None
            status, _ = org("POST", f"/api/v1/rounds/{rid}/start")
            must(f"session {s + 1} started", status == 200, str(status))
            for p in phones:
                p.start(rid)
            t_zero = time.monotonic() + 3
            events = {"message": False, "hands": False, "paused": False}

            def organizer_loop(t_zero=t_zero, rid=rid, s=s, events=events):
                last_tick = time.monotonic()
                last_sample = 0.0
                while not _STOP.is_set() and time.monotonic() - t_zero < seconds:
                    now = time.monotonic() - t_zero
                    if now - last_sample >= 30:
                        last_sample = now
                        entry = sample(rid, f"s{s + 1}+{int(now)}s")
                        line = " ".join(
                            f"T{n}:{v['readiness'][:1] if v['readiness'] else '?'}"
                            f"{'/' + ','.join(v['reasons']) if v['reasons'] else ''}"
                            f"(src {v['live_source_slot']})"
                            for n, v in sorted((entry.get("tables") or {}).items())
                        )
                        print(f"    [{entry['t']}] pool wait {entry['pool_max_wait_ms']} ms  {line}")
                    if time.monotonic() - last_tick >= 60:
                        last_tick = time.monotonic()
                        facilitator_tick()
                    if not events["message"] and now >= 120:
                        events["message"] = True
                        org("POST", f"/api/v1/rounds/{rid}/messages", {"kind": "TIME_LEFT", "minutes": max(1, minutes - 2)})
                    if not events["hands"] and now >= 60:
                        events["hands"] = True
                        for table in (1, 2, 3):
                            fac = facilitators.get(table)
                            if fac and fac.connected:
                                phone("POST", "/api/v1/public/facilitator/help", {"kind": "PROCESS"}, token=fac.token, phase="fac-help")
                    if s == 0 and paused_table and not events["paused"] and now >= 60:
                        events["paused"] = True
                        nonlocal paused_at
                        org("POST", f"/api/v1/assemblies/{aid}/tables/{paused_table}/facilitation", {"level": "off"})
                        paused_at = time.time()
                    for table, fac in facilitators.items():
                        fac.tick(policies[table])
                    _STOP.wait(10)

            org_thread = threading.Thread(target=organizer_loop, daemon=True)
            org_thread.start()
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(phones)) as pool:
                futures = [pool.submit(p.run_session, s, t_zero) for p in phones]
                for f in futures:
                    try:
                        f.result()
                    except Exception as exc:  # noqa: BLE001 - a dead thread is a failure, not a crash
                        with _LOCK:
                            FAILURES.append(f"phone thread: {type(exc).__name__}: {exc}")
            org_thread.join(timeout=30)
            # one last read on every phone: a banner sent in the final minute
            # lands here rather than being missed by the 30 s poll cadence
            for p in phones:
                p.poll_status()

            # the stall chain, read from the samples of this session
            if s == 0 and any(p.stall for p in phones):
                mid = [e for e in SAMPLES if e["label"].startswith("s1+") and 120 <= int(e["label"][3:-1]) <= 210]
                silent = any("CAPTURE_SILENT" in (e.get("tables") or {}).get(1, {}).get("reasons", []) for e in mid)
                failed_over = any((e.get("tables") or {}).get(1, {}).get("live_source_slot") == 2 for e in mid)
                check("table 1: CAPTURE_SILENT reached the Live tab during the stall", silent,
                      str([e.get("tables", {}).get(1, {}).get("reasons") for e in mid]))
                check("table 1: the captions failed over to recorder B during the stall", failed_over,
                      str([e.get("tables", {}).get(1, {}).get("live_source_slot") for e in mid]))
                alerts = facilitators[1].recorder_alerts
                check("table 1: the facilitator's phone was told which recorder went quiet",
                      any(a["alerts"] for a in alerts), str(len(alerts)))

            # delivery of the organizer's message
            status, listed = org("GET", f"/api/v1/rounds/{rid}/messages")
            time_left = [m for m in (listed if isinstance(listed, list) else []) if m.get("kind") == "TIME_LEFT"]
            if time_left:
                check(f"session {s + 1}: TIME_LEFT reached every table", time_left[0].get("not_seen_by") == [],
                      json.dumps({"seen": time_left[0].get("seen_by"), "not": time_left[0].get("not_seen_by")}))
            status, monitor = org("GET", f"/api/v1/rounds/{rid}/monitor")
            hands = [t["number"] for t in monitor.get("tables", []) if t.get("help_request")]
            expected_hands = [t for t in (1, 2, 3) if t <= tables and facilitators[t].connected]
            check(f"session {s + 1}: hands raised from facilitator phones show on the Live tab",
                  sorted(hands) == expected_hands, f"{sorted(hands)} vs {expected_hands}")
            for t in monitor.get("tables", []):
                if t.get("help_request"):
                    org("POST", f"/api/v1/help-requests/{t['help_request']['id']}/acknowledge")

            status, _ = org("POST", f"/api/v1/rounds/{rid}/end")
            for p in phones:
                p.complete()
            status, log_ = org("GET", f"/api/v1/rounds/{rid}/interventions")
            interventions_by_session[rid] = log_ if isinstance(log_, list) else []
            per_table: dict[int, int] = {}
            for item in interventions_by_session[rid]:
                per_table[item.get("table_number")] = per_table.get(item.get("table_number"), 0) + 1
            print(f"  interventions this session: {per_table or 'none'}")
            check(f"session {s + 1}: Normal cap holds (≤ 4 per table)", all(n <= 4 for n in per_table.values()), str(per_table))
            if s == 0 and paused_table and paused_at:
                after_pause = [i for i in interventions_by_session[rid]
                               if i.get("table_number") == paused_table and _created_after(i, paused_at)]
                check(f"table {paused_table}: nothing from the assistant after Pause AI", not after_pause, str(len(after_pause)))
            for table in range(1, tables + 1):
                fac = facilitators[table]
                mine = [i for i in interventions_by_session[rid] if i.get("table_number") == table]
                if not mine:
                    continue
                to_fac = [i for i in mine if i.get("delivered_to") == "facilitator"]
                to_table = [i for i in mine if i.get("delivered_to") == "table"]
                if fac.connected:
                    check(f"session {s + 1} table {table}: advice went to the facilitator's phone as cards, not banners",
                          len(to_table) == 0, f"cards={len(to_fac)} banners={len(to_table)}")
                else:
                    check(f"session {s + 1} table {table}: with no facilitator phone the advice reached the table phones",
                          len(to_table) >= 1 and len(BANNERS.get(table, [])) >= 1,
                          f"banners={len(to_table)} seen on phones={len(BANNERS.get(table, []))}")
            if s == 0 and 1 in CARDS and facilitators[1].sent_one:
                check("table 1: Send to table turned a card into a banner on the table phones",
                      len(BANNERS.get(1, [])) >= 1, str(len(BANNERS.get(1, []))))
            if s + 1 < sessions:
                status, mixed = org("POST", f"/api/v1/rounds/{rounds[s + 1]['id']}/assignments/remix", {"goal": "new_people"})
                check("New seating between the sessions", status == 200 and mixed.get("seated", 0) >= tables * (people - 1) - 2,
                      json.dumps({k: mixed.get(k) for k in ("goal", "seated", "repeated_pairs")}))

        # the tail: transcripts, analyses, the synthesis at closing
        print("\nwaiting for transcription and analysis…")
        budget = max(15 * 60, total_phones * sessions * minutes * 8)
        deadline = time.monotonic() + budget
        while time.monotonic() < deadline:
            done = 0
            for round_ in rounds:
                status, findings = org("GET", f"/api/v1/rounds/{round_['id']}/findings", timeout=60)
                if status == 200 and findings.get("round_summary"):
                    done += 1
            print(f"    sessions analysed: {done}/{len(rounds)}")
            if done == len(rounds):
                break
            time.sleep(30)
        check("every session was analysed within the budget", done == len(rounds), f"{done}/{len(rounds)}")
        status, _ = org("POST", f"/api/v1/assemblies/{aid}/close", {})
        check("assembly closed", status in (200, 204), str(status))
        synthesis = None
        for _ in range(20):
            status, report = org("GET", f"/api/v1/assemblies/{aid}/report", timeout=120)
            synthesis = report.get("synthesis") if status == 200 else None
            if synthesis or sessions < 2:
                break
            time.sleep(15)
        if sessions >= 2:
            check("the report carries the synthesis across the sessions", bool(synthesis), str(type(synthesis).__name__))
        check("report headings say Sessione N", status == 200 and report["rounds"][0]["heading"].startswith("Sessione 1"),
              report["rounds"][0].get("heading") if status == 200 else str(status))
        check("report carries the speaking comparison", isinstance(report["rounds"][0].get("speaking_comparison"), list))
        status, pdf = org("GET", f"/api/v1/assemblies/{aid}/report.pdf", raw=True, timeout=180)
        check("report.pdf renders", status == 200 and pdf[:4] == b"%PDF", str(status))
        status, files = org("GET", f"/api/v1/assemblies/{aid}/files")
        low = [(e["table_number"], e["coverage"]["percent"]) for r in files.get("rounds", []) for e in r["tables"]
               if e.get("coverage") and e["coverage"]["percent"] < 95]
        print(f"  recordings below 95 % coverage: {low or 'none'} (table 1 recorder A stalled on purpose)")
        return summarize(assembly, interventions_by_session)
    finally:
        _STOP.set()
        if assembly and not keep:
            status, _ = org("DELETE", f"/api/v1/assemblies/{assembly['id']}")
            print(f"\n  rehearsal assembly deleted: {status}")
        elif assembly:
            print(f"\n  kept: assembly {assembly['id']}")
        restore_provider(previous_provider)


def _created_after(item: dict, when: float) -> bool:
    stamp = item.get("created_at") or ""
    try:
        from datetime import datetime
        created = datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return False
    return created > when


def summarize(assembly: dict, interventions: dict[str, list[dict]]) -> int:
    print("\n" + "=" * 68)
    print(f"assembly : {assembly['id']}  {assembly['name']}")
    print("\n-- request latency by phase (through the proxy unless organizer/health/monitor/tick) " + "-" * 4)
    for phase, values in sorted(TIMINGS.items()):
        values = sorted(values)
        p95 = values[min(len(values) - 1, int(len(values) * 0.95))]
        print(f"  {phase:<14} n={len(values):<5} p50={values[len(values) // 2] * 1000:6.0f}ms "
              f"p95={p95 * 1000:7.0f}ms max={values[-1] * 1000:7.0f}ms")
    if SAMPLES:
        worst = max((s.get("pool_max_wait_ms") or 0) for s in SAMPLES)
        slow = max((s.get("pool_slow_waits") or 0) for s in SAMPLES)
        print(f"\n-- db pool: worst wait {worst} ms, slow waits {slow} (from /health)")
    if TICKS:
        secs = sorted(t["seconds"] for t in TICKS)
        delivered = sum(max(0, t["delivered"]) for t in TICKS)
        print(f"-- assistant ticks: {len(TICKS)}, median {secs[len(secs) // 2]:.1f} s, max {secs[-1]:.1f} s, "
              f"delivered {delivered}")
    total = sum(len(v) for v in interventions.values())
    print(f"-- interventions (model calls that spoke): {total}; cards seen: "
          f"{sum(len(v) for v in CARDS.values())}; banners seen on table phones: {sum(len(v) for v in BANNERS.values())}")
    if CAPTION_POLLS:
        print("-- live captions: polls with lines per recorder")
        for name, polls in sorted(CAPTION_POLLS.items()):
            if polls:
                print(f"  {name}: {sum(polls)}/{len(polls)}")
    print("\n-- checks " + "-" * 58)
    for line in CHECKS:
        print("  " + line)
    print("\n-- failures " + "-" * 56)
    for failure in FAILURES[:30] or ["none"]:
        print("  " + failure)
    ok = not FAILURES
    print("\n" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main() -> int:
    global BASE
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--smoke", action="store_true", help="2 tables × 2 phones × 90 s, one session")
    parser.add_argument("--yes", action="store_true", help="required for the full rehearsal")
    parser.add_argument("--tables", type=int, default=5)
    parser.add_argument("--people", type=int, default=10)
    parser.add_argument("--minutes", type=int, default=6)
    parser.add_argument("--sessions", type=int, default=2)
    parser.add_argument("--keep", action="store_true", help="do not delete the rehearsal assembly")
    parser.add_argument("--no-vosk", action="store_true", help="leave the live engine as configured")
    args = parser.parse_args()
    BASE = discover_base()
    print(f"target: {BASE} ({CONTAINER}); phones via {PROXY}")
    workdir = pathlib.Path("/tmp/citizens-load-j")
    if args.smoke:
        print("SMOKE: 2 tables × 2 phones, 3 people each, one session of 2 min\n")
        return run_smoke(workdir, args)
    if not args.yes:
        print("This runs a real rehearsal on the live instance (audio through the proxy, the analysis "
              "model and the AI assistant called for real). Run --smoke first, then --yes.", file=sys.stderr)
        return 2
    phones_per_table = [2 + (i % 2) for i in range(args.tables)]
    print(f"FULL REHEARSAL: {args.tables} tables, phones per table {phones_per_table}, {args.people} people each, "
          f"{args.sessions} sessions × {args.minutes} min\n")
    return run(args.tables, phones_per_table, args.people, args.sessions, args.minutes, workdir,
               args.keep, not args.no_vosk)


def run_smoke(workdir: pathlib.Path, args) -> int:
    # 90 s is below the stall window and the time-nudge window: the smoke proves
    # the flows (join, consent, record, tick, messages, hands, close), not the load
    return run(2, [2, 2], 3, 1, 2, workdir, args.keep, not args.no_vosk)


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        _STOP.set()
