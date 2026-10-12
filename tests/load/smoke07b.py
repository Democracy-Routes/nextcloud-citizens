# ruff: noqa: E501 — a smoke script reads best as one check per line
"""Smoke the 0.7 branch on the dev instance, through the real proxy.

Consent (shared phone and own phone, refusal → moved, two boxes, quotations
withheld), messages, help, guards' peek, event kit, participant page, the
facilitator's phone, the AI assistant's switches, New table only in a
Session, "Sessione N" headings — and, unless --no-captions, a three-minute
two-phone segment on the configured live engine with a caption takeover.

Organizer routes: signed with the ExApp secret straight at the container.
Phone routes: through the real Nextcloud proxy. Creates one assembly (and one
Session for the captions segment) and deletes them at the end.

    python3 tests/load/smoke07b.py [--no-captions]
"""
import argparse
import base64
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = pathlib.Path("/root/NextCloud-Citizen")
SECRET = (REPO / ".app_secret").read_text().strip()
IP = subprocess.check_output(
    ["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}", "nc_app_citizens"],
    text=True,
).split()[0]
ORG = f"http://{IP}:23000"
PROXY = "https://cloud.democracyinnovators.com/index.php/apps/app_api/proxy/citizens"
ORGANIZER = "smoke-0.7b"
STEPS: list[str] = []


def org(method, path, data=None, raw=False):
    headers = {
        "EX-APP-ID": "citizens", "EX-APP-VERSION": "1.0.0",
        "AUTHORIZATION-APP-API": base64.b64encode(f"{ORGANIZER}:{SECRET}".encode()).decode(),
    }
    body = None
    if data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data).encode()
    req = urllib.request.Request(ORG + path, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            payload = r.read()
            status = r.status
    except urllib.error.HTTPError as exc:
        return exc.code, (exc.read() if raw else json.loads(exc.read() or b"{}"))
    return status, (payload if raw else (json.loads(payload) if payload else {}))


def phone(method, path, data=None, token=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None
    if data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data).encode()
    req = urllib.request.Request(PROXY + path, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            payload = r.read()
            status = r.status
    except urllib.error.HTTPError as exc:
        raw = exc.read() or b"{}"
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, {"raw": raw[:200].decode(errors="replace")}
    return status, (json.loads(payload) if payload else {})


def phone_raw(path, body: bytes, token: str, segment: int = 0):
    """A chunk upload through the proxy, as the recorder engine sends it."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/octet-stream",
        "X-Chunk-SHA256": hashlib.sha256(body).hexdigest(),
        "X-Chunk-Segment": str(segment),
    }
    req = urllib.request.Request(PROXY + path, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, {"raw": (exc.read() or b"")[:200].decode(errors="replace")}


WEBM_CLUSTER_ID = b"\x1f\x43\xb6\x75"


def phone_chunks(minutes: int, offset_minutes: int = 0) -> list[bytes]:
    """Ten-second-ish chunks cut at WebM Cluster boundaries from a real past
    recording — what a phone's MediaRecorder produces, so a decoder seeded
    with the header and fed a later chunk decodes it (live_audio.container_header)."""
    listing = subprocess.check_output(
        ["docker", "exec", "nc_app_citizens", "sh", "-c",
         'for f in $(find /data/assembled -type f -name "*.webm"); do '
         'd=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f"); echo "$d $f"; done'],
        text=True,
    )
    sources = sorted(
        ((float(d), f) for d, _, f in (line.partition(" ") for line in listing.splitlines()) if d.replace(".", "", 1).isdigit()),
        reverse=True,
    )
    sources = [(d, f) for d, f in sources if d >= 900]
    if not sources:
        sys.exit("no long recording in /data/assembled to replay")
    duration, path = sources[0]
    local = pathlib.Path("/tmp/citizens-smoke07b-source.webm")
    if not local.exists():
        subprocess.check_call(["docker", "cp", f"nc_app_citizens:{path}", str(local)])
    blob = local.read_bytes()
    offsets = []
    at = blob.find(WEBM_CLUSTER_ID)
    while at >= 0:
        offsets.append(at)
        at = blob.find(WEBM_CLUSTER_ID, at + 1)
    header = blob[: offsets[0]]
    bytes_per_second = len(blob) / duration
    # clusters grouped into ~10 s of bytes, starting `offset_minutes` in
    start = next((i for i, o in enumerate(offsets) if o >= offset_minutes * 60 * bytes_per_second), 0)
    chunks, piece_start, target = [], offsets[start], offsets[start] + 10 * bytes_per_second
    for o in offsets[start + 1:]:
        if o >= target:
            chunks.append(blob[piece_start:o])
            piece_start, target = o, o + 10 * bytes_per_second
        if len(chunks) >= minutes * 6:
            break
    # the first chunk carries the container header, as the phone's does
    chunks[0] = header + chunks[0]
    return chunks


def ok(label, condition, detail=""):
    STEPS.append(("PASS " if condition else "FAIL ") + label + (f"  [{detail}]" if detail else ""))
    if not condition:
        print("\n".join(STEPS))
        sys.exit(f"FAILED at: {label} {detail}")


def tok(url, route="join"):
    return re.search(rf"#/{route}/(.+)$", url).group(1)


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--no-captions", action="store_true", help="skip the three-minute live captions segment")
ARGS = parser.parse_args()
aid = None
caid = None
try:
    # 1. an organized assembly, consent required (as the wizard sends it)
    code, created = org("POST", "/api/v1/assemblies", {
        "name": "SMOKE 0.7b consent", "language": "it", "default_table_count": 2,
        "participant_consent": "required",
        "rounds": [{"title": "Problemi", "question": "Cosa non funziona?", "objective": "Una lista", "duration_minutes": 20}],
    })
    ok("assembly created with participant_consent=required", code == 201 and created["participant_consent"] == "required", str(code))
    aid, rid = created["id"], created["rounds"][0]["id"]
    org("POST", f"/api/v1/rounds/{rid}/start")

    # 2. phone A joins table 1 through the proxy; its join carries the consent state
    code, a = phone("POST", "/api/v1/public/join", {"token": tok(created["invites"][0]["url"])})
    ok("phone A joins", code == 200 and a["consent"] == {"mode": "required", "registered": 0, "consenting": 0, "refusing": 0, "can_record": False}, json.dumps(a.get("consent")))
    tA = a["session_token"]

    # 3. the notice, in Italian, hashed; start is refused until someone consents
    code, notice = phone("GET", "/api/v1/public/recorder/consent-notice", token=tA)
    ok("consent notice rendered in Italian", code == 200 and notice["language"] == "it" and any("registra questa discussione" in p for p in notice["paragraphs"]), str(code))
    code, blocked = phone("POST", "/api/v1/public/recorder/start", {"round_id": rid, "mime_type": "audio/webm"}, token=tA)
    ok("start refused: PARTICIPANT_CONSENT_REQUIRED", code == 409 and blocked["detail"]["code"] == "PARTICIPANT_CONSENT_REQUIRED", json.dumps(blocked))
    code, mon = org("GET", f"/api/v1/rounds/{rid}/monitor")
    t1 = next(t for t in mon["tables"] if t["number"] == 1)
    ok("Live tab: table 1 blocked for missing consent", any(r["code"] == "PARTICIPANT_CONSENT_MISSING" for r in t1["readiness"]["reasons"]), json.dumps(t1["readiness"]))

    # 4. one refusal, one consent on the shared phone
    act = {"notice_hash": notice["hash"], "notice_read": True, "recording_consent": True,
           "transcription_consent": True, "analysis_consent": True, "publication_consent": False}
    code, refused = phone("POST", "/api/v1/public/recorder/participants", {**act, "name": "Smoke Anna", "recording_consent": False, "transcription_consent": False, "analysis_consent": False}, token=tA)
    ok("a refusal is recorded, can_record false", code == 201 and refused["can_record"] is False, str(code))
    code, agreed = phone("POST", "/api/v1/public/recorder/participants", {**act, "name": "Smoke Bruno", "email": "bruno@example.org"}, token=tA)
    ok("a consent is recorded, but Anna refused and is still seated: the table waits",
       code == 201 and agreed["table"]["can_record"] is False and agreed["table"]["refusing"] == 1
       and agreed["table"]["consenting"] == 1, json.dumps(agreed.get("table")))
    code, blocked = phone("POST", "/api/v1/public/recorder/start", {"round_id": rid, "mime_type": "audio/webm"}, token=tA)
    ok("start refused: PARTICIPANT_REFUSED", code == 409 and blocked["detail"]["code"] == "PARTICIPANT_REFUSED", json.dumps(blocked))
    code, mon = org("GET", f"/api/v1/rounds/{rid}/monitor")
    t1 = next(t for t in mon["tables"] if t["number"] == 1)
    ok("Live tab: PARTICIPANT_REFUSED blocks table 1", any(r["code"] == "PARTICIPANT_REFUSED" for r in t1["readiness"]["reasons"]), json.dumps(t1["readiness"]))
    code, roster = phone("GET", "/api/v1/public/recorder/consent-notice", token=tA)
    ok("the roster says who refused", [(p["name"], p["refused"]) for p in roster["participants"]] == [("Smoke Anna", True), ("Smoke Bruno", False)], json.dumps(roster["participants"]))
    code, moved = phone("POST", f"/api/v1/public/recorder/participants/{refused['participant']['id']}/moved", token=tA)
    ok("Anna marked as moved to a table that is not recorded", code == 200 and moved["table"]["can_record"] is True and moved["table"]["refusing"] == 0, json.dumps(moved))
    code, started = phone("POST", "/api/v1/public/recorder/start", {"round_id": rid, "mime_type": "audio/webm"}, token=tA)
    ok("start allowed now", code == 201, str(code))
    # Bruno withdraws and changes his mind again: two further acts, newest counts
    code, withdrawn = phone("POST", f"/api/v1/public/recorder/participants/{agreed['participant']['id']}/consent",
                            {"notice_hash": notice["hash"], "notice_read": True}, token=tA)
    ok("Bruno withdraws: table blocked again", code == 201 and withdrawn["table"]["refusing"] == 1 and withdrawn["table"]["can_record"] is False, json.dumps(withdrawn.get("table")))
    code, back = phone("POST", f"/api/v1/public/recorder/participants/{agreed['participant']['id']}/consent",
                       {**act, "publication_consent": True}, token=tA)
    ok("Bruno changed his mind: table may record", code == 201 and back["table"]["can_record"] is True, json.dumps(back.get("table")))
    code, other = phone("POST", "/api/v1/public/join", {"token": tok(created["invites"][1]["url"])})
    code, foreign = phone("POST", f"/api/v1/public/recorder/participants/{agreed['participant']['id']}/moved", token=other["session_token"])
    ok("another table's phone cannot act on Bruno (404)", code == 404, str(code))

    # 5. own-phone registration at table 2
    code, b = phone("POST", "/api/v1/public/join", {"token": tok(created["invites"][1]["url"])})
    tB = b["session_token"]
    code, card = phone("POST", "/api/v1/public/recorder/capabilities", {"purpose": "REGISTER_PARTICIPANT"}, token=tB)
    ok("table 2 makes a REGISTER_PARTICIPANT code", code == 201 and "#/register/" in card["url"] and card["table_number"] == 2, str(code))
    rtok = tok(card["url"], "register")
    code, peek = phone("POST", "/api/v1/public/capabilities/peek", {"token": rtok})
    ok("peek says what the code is", code == 200 and peek["purpose"] == "REGISTER_PARTICIPANT" and peek["table_number"] == 2, json.dumps(peek))
    code, rn = phone("POST", "/api/v1/public/register/notice", {"token": rtok})
    ok("register/notice: event, table 2 green, notice", code == 200 and rn["table_number"] == 2 and rn["color_key"] == "green" and rn["hash"] == notice["hash"], str(code))
    code, reg = phone("POST", "/api/v1/public/register", {**act, "token": rtok, "name": "Smoke Giulia", "notice_hash": rn["hash"]})
    ok("own-phone registration returns a participant token", code == 201 and reg["participant_token"] and reg["consent"]["method"] == "SELF_PHONE", str(code))
    pT = reg["participant_token"]
    code, roster = phone("GET", "/api/v1/public/recorder/consent-notice", token=tB)
    ok("table 2's roster shows Giulia", [p["name"] for p in roster["participants"]] == ["Smoke Giulia"], json.dumps(roster["participants"]))
    code, ps = phone("GET", "/api/v1/public/participant/status", token=pT)
    ok("participant page: table 2, consent, no report yet", code == 200 and ps["table_number"] == 2 and ps["consent"]["recording"] and ps["report_available"] is False, json.dumps(ps)[:200])
    code, _ = phone("POST", "/api/v1/public/join", {"token": rtok})
    ok("the registration code never joins (409)", code == 409, str(code))

    # 6. messages: organizer → tables, receipt, delivery
    code, msg = org("POST", f"/api/v1/rounds/{rid}/messages", {"kind": "TIME_LEFT", "minutes": 5})
    ok("TIME_LEFT worded in Italian", code == 201 and msg["text"] == "5 minuti rimasti", json.dumps(msg))
    code, stA = phone("GET", "/api/v1/public/recorder/status", token=tA)
    ok("phone A sees the message", [m["id"] for m in stA["messages"]] == [msg["id"]], json.dumps(stA.get("messages")))
    code, _ = phone("POST", "/api/v1/public/recorder/messages/seen", {"message_id": msg["id"]}, token=tA)
    ok("A posts a receipt", code == 200, str(code))
    code, listed = org("GET", f"/api/v1/rounds/{rid}/messages")
    ok("delivery: table 1 seen, table 2 not yet", listed[0]["seen_by"] == [1] and listed[0]["not_seen_by"] == [2], json.dumps(listed[0]))

    # 7. help: table 2 raises its hand, organizer acknowledges
    code, hand = phone("POST", "/api/v1/public/recorder/help", {"kind": "TECHNICAL"}, token=tB)
    ok("table 2 raises its hand", code == 201, str(code))
    code, mon = org("GET", f"/api/v1/rounds/{rid}/monitor")
    t2 = next(t for t in mon["tables"] if t["number"] == 2)
    ok("Live tab: HELP_REQUESTED on table 2", t2["help_request"]["id"] == hand["id"] and any(r["code"] == "HELP_REQUESTED" for r in t2["readiness"]["reasons"]), json.dumps(t2["readiness"]))
    code, ack = org("POST", f"/api/v1/help-requests/{hand['id']}/acknowledge")
    ok("acknowledged", code == 200 and ack["acknowledged_at"], str(code))
    code, stB = phone("GET", "/api/v1/public/recorder/status", token=tB)
    ok("phone B sees the acknowledgement", stB["help"] and stB["help"]["acknowledged_at"], json.dumps(stB.get("help")))

    # 8. organizer list + event kit
    code, people = org("GET", f"/api/v1/assemblies/{aid}/participants")
    by = {p["name"]: p for p in people}
    ok("participants list carries consent and source", by["Smoke Anna"]["consent"]["recording"] is False and by["Smoke Giulia"]["source"] == "SELF_PHONE" and by["Smoke Bruno"]["email"] == "bruno@example.org", json.dumps(people)[:300])
    code, pdf = org("GET", f"/api/v1/assemblies/{aid}/event-kit.pdf", raw=True)
    ok("event kit PDF renders", code == 200 and pdf.startswith(b"%PDF"), str(code))

    # 8b. phase A: the notice carries its acceptance sentence; the register exports
    ok("notice 2026-10.3: the processing sentence and the quotations sentence are its last two paragraphs",
       notice["version"] == "2026-10.3" and notice["acceptance"] == notice["paragraphs"][-2]
       and notice["acceptance_quotations"] == notice["paragraphs"][-1]
       and "Registrandoti dichiari" in notice["acceptance"] and "citazioni" in notice["acceptance_quotations"]
       and any("non viene registrato" in p for p in notice["paragraphs"]), notice["version"])
    code, csv_body = org("GET", f"/api/v1/assemblies/{aid}/consent-register.csv", raw=True)
    ok("consent register CSV lists every act (Bruno three times)", code == 200 and csv_body.count(b"Smoke Bruno") == 3
       and b"Smoke Giulia" in csv_body and b"SELF_PHONE" in csv_body, str(csv_body.count(b"Smoke Bruno")))
    code, reg_pdf = org("GET", f"/api/v1/assemblies/{aid}/consent-register.pdf", raw=True)
    ok("consent register PDF renders", code == 200 and reg_pdf.startswith(b"%PDF"), str(code))

    # 8c. phase A: a Record-now session detects its language and has nobody to call
    code, rn = org("POST", "/api/v1/sessions/record-now", {"language": "en"})
    ok("record now creates a language_auto session", code == 200 or code == 201, str(code))
    code, rn_container = org("GET", f"/api/v1/assemblies/{rn['container_id']}")
    ok("record now container is language_auto", rn_container.get("language_auto") is True, json.dumps(rn_container.get("language_auto")))
    code, rn_phone = phone("POST", "/api/v1/public/join", {"token": tok(rn["recorder_url"])})
    ok("record-now phone joins", code == 200, str(code))
    code, refused = phone("POST", "/api/v1/public/recorder/help", {"kind": "TECHNICAL"}, token=rn_phone["session_token"])
    ok("need help is refused on a Session (409)", code == 409, str(code))
    code, card_s = phone("POST", "/api/v1/public/recorder/capabilities", {"purpose": "ADD_TABLE", "round_id": rn["session_id"]}, token=rn_phone["session_token"])
    ok("New table from a phone: allowed in a Session (201)", code == 201 and card_s["purpose"] == "ADD_TABLE", str(code))
    code, card_a = phone("POST", "/api/v1/public/recorder/capabilities", {"purpose": "ADD_TABLE", "round_id": rid}, token=tA)
    ok("New table from a phone: refused in an organized assembly (409 ORGANIZER_ADDS_TABLES)",
       code == 409 and card_a["detail"]["code"] == "ORGANIZER_ADDS_TABLES", json.dumps(card_a))
    code, _ = org("DELETE", f"/api/v1/assemblies/{rn['container_id']}")
    ok("record-now smoke session deleted", code == 204, str(code))

    # 8d. phase B: pre-registration at home, seated at the door by name
    code, link = org("POST", f"/api/v1/assemblies/{aid}/registration-link")
    ok("pre-registration link made", code == 200 and "#/register/" in link["url"] and link["registered"]["total"] == 0, json.dumps(link)[:200])
    code, again = org("GET", f"/api/v1/assemblies/{aid}/registration-link")
    ok("the same link comes back", again["url"] == link["url"], str(code))
    ptok = tok(link["url"], "register")
    code, pn = phone("POST", "/api/v1/public/register/notice", {"token": ptok})
    ok("register/notice: no table yet", code == 200 and pn["table_number"] is None and pn["color_key"] is None, json.dumps(pn)[:200])
    code, pre = phone("POST", "/api/v1/public/register", {**act, "token": ptok, "name": "Smoke Carla", "notice_hash": pn["hash"]})
    ok("pre-registration recorded (PRE_REGISTRATION)", code == 201 and pre["consent"]["method"] == "PRE_REGISTRATION", json.dumps(pre)[:200])
    cT = pre["participant_token"]
    code, cs = phone("GET", "/api/v1/public/participant/status", token=cT)
    ok("participant page before seating: no table", code == 200 and cs["table_number"] is None, json.dumps(cs)[:200])
    code, found = phone("GET", "/api/v1/public/recorder/participants/search?q=car", token=tB)
    ok("table 2 finds Carla by name", code == 200 and [p["name"] for p in found] == ["Smoke Carla"], json.dumps(found)[:200])
    code, seated = phone("POST", f"/api/v1/public/recorder/participants/{found[0]['id']}/seat", token=tB)
    ok("seat here", code == 200, json.dumps(seated)[:200])
    code, roster = phone("GET", "/api/v1/public/recorder/consent-notice", token=tB)
    ok("table 2's roster shows Giulia and Carla", sorted(p["name"] for p in roster["participants"]) == ["Smoke Carla", "Smoke Giulia"], json.dumps(roster["participants"]))
    code, seated2 = phone("POST", f"/api/v1/public/recorder/participants/{found[0]['id']}/seat", token=tB)
    ok("seating twice is refused (409)", code == 409, str(code))
    code, link2 = org("GET", f"/api/v1/assemblies/{aid}/registration-link")
    ok("registration counts: 1 registered, 1 seated", link2["registered"]["total"] == 1 and link2["registered"]["seated"] == 1, json.dumps(link2["registered"]))

    # 8e. phase B: a second session, remixed to meet new people; Carla learns her next table
    code, r2 = org("POST", f"/api/v1/assemblies/{aid}/rounds", {"title": "Proposte", "question": "Cosa proponiamo?", "duration_minutes": 20})
    ok("second session added", code == 201, str(code))
    code, mixed = org("POST", f"/api/v1/rounds/{r2['id']}/assignments/remix", {"goal": "new_people"})
    ok("remix seats everyone registered at the tables", code == 200 and mixed["goal"] == "new_people" and mixed["seated"] >= 3, json.dumps({k: mixed[k] for k in ("goal", "seated", "repeated_pairs")}))
    code, cs = phone("GET", "/api/v1/public/participant/status", token=cT)
    ok("participant page announces the next table", cs.get("next_table") and cs["next_table"]["round_title"] == "Proposte" and cs["next_table"]["table_number"] in (1, 2), json.dumps(cs.get("next_table")))
    code, fx = org("GET", f"/api/v1/rounds/{rid}/findings")
    ok("findings carry the speaking comparison", code == 200 and isinstance(fx.get("speaking_comparison"), list), str(code))
    code, syn = org("POST", f"/api/v1/assemblies/{aid}/synthesis")
    ok("synthesis refused with fewer than two summaries (409)", code == 409, str(code))

    # 8f. phase C: the facilitator's own phone beside table 1
    code, fcard = phone("POST", "/api/v1/public/recorder/capabilities", {"purpose": "FACILITATE_TABLE"}, token=tA)
    ok("table 1 makes a FACILITATE_TABLE code", code == 201 and "#/facilitate/" in fcard["url"] and fcard["table_number"] == 1, str(code))
    ftok = tok(fcard["url"], "facilitate")
    code, fj = phone("POST", "/api/v1/public/facilitate", {"token": ftok})
    ok("facilitator phone joins table 1", code == 200 and fj["table_number"] == 1 and fj["round"]["status"] == "ACTIVE" and fj["round"]["question"] == "Cosa non funziona?", json.dumps({k: fj.get(k) for k in ("table_number", "round")})[:200])
    fT = fj["facilitator_token"]
    ok("facilitator sees the roster (Anna moved away) and the recorder count", [p["name"] for p in fj["participants"]] == ["Smoke Bruno"] and fj["recorders"] == 1, json.dumps(fj["participants"]))
    ok("facilitator status carries recorder alerts (none yet)", fj.get("recorder_alerts") == [], json.dumps(fj.get("recorder_alerts")))
    ok("speaking balance says not available; AI off by default", fj["speaking"] is None and fj["capabilities"]["ai_facilitator"] is False and fj["advice"] == [], json.dumps(fj["capabilities"]))
    code, _ = phone("POST", "/api/v1/public/join", {"token": ftok})
    ok("the facilitator code never makes a recorder (409)", code == 409, str(code))
    code, fp = phone("POST", "/api/v1/public/facilitator/prompt", {"text": "Hanno parlato tutti?"}, token=fT)
    ok("facilitator writes a prompt to the table", code == 201 and fp["author"] == "facilitator", json.dumps(fp)[:160])
    code, stA = phone("GET", "/api/v1/public/recorder/status", token=tA)
    ok("table 1's phone receives the facilitator's prompt", any(m["text"] == "Hanno parlato tutti?" and m.get("author") == "facilitator" for m in stA["messages"]), json.dumps(stA.get("messages"))[:200])
    code, stB = phone("GET", "/api/v1/public/recorder/status", token=tB)
    ok("table 2's phone does not", not any(m["text"] == "Hanno parlato tutti?" for m in stB["messages"]), json.dumps(stB.get("messages"))[:200])
    code, fh = phone("POST", "/api/v1/public/facilitator/help", {"kind": "PROCESS"}, token=fT)
    ok("facilitator raises the table's hand", code == 201, str(code))
    code, mon = org("GET", f"/api/v1/rounds/{rid}/monitor")
    t1 = next(t for t in mon["tables"] if t["number"] == 1)
    ok("Live tab shows table 1's hand (PROCESS) and the AI level", (t1["help_request"] or {}).get("kind") == "PROCESS" and t1.get("ai_facilitator") == "off", json.dumps({"help": t1.get("help_request"), "ai": t1.get("ai_facilitator")}))
    org("POST", f"/api/v1/help-requests/{fh['id']}/acknowledge")
    code, rcode = phone("POST", "/api/v1/public/facilitator/codes", {"purpose": "REGISTER_PARTICIPANT"}, token=fT)
    ok("facilitator makes a registration code for table 1", code == 201 and "#/register/" in rcode["url"] and rcode["table_number"] == 1, str(code))
    code, hb = phone("POST", "/api/v1/public/facilitator/heartbeat", token=fT)
    ok("facilitator heartbeat", code == 200, str(code))

    # 8g. phase C: the AI facilitator's switches (no model call in the smoke)
    code, lvl = phone("POST", "/api/v1/public/recorder/facilitator", {"level": "light"}, token=tA)
    ok("table 1 sets its own AI level", code == 200 and lvl["level"] == "light" and lvl["override"] == "light", json.dumps(lvl))
    code, mon = org("GET", f"/api/v1/rounds/{rid}/monitor")
    t1 = next(t for t in mon["tables"] if t["number"] == 1)
    ok("Live tab sees the table's level", t1.get("ai_facilitator") == "light", str(t1.get("ai_facilitator")))
    code, paused = org("POST", f"/api/v1/assemblies/{aid}/tables/1/facilitation", {"level": "off"})
    ok("organizer pauses the AI at table 1", code == 200 and paused["level"] == "off", json.dumps(paused))
    code, up = org("PUT", f"/api/v1/assemblies/{aid}", {"ai_facilitator": "normal"})
    ok("assembly level set to normal; default reported", code == 200 and up["ai_facilitator"] == "normal" and up.get("ai_facilitator_default") in ("off", "light", "normal", "active"), json.dumps({k: up.get(k) for k in ("ai_facilitator", "ai_facilitator_default", "ai_facilitator_configured")}))
    code, fs = phone("GET", "/api/v1/public/facilitator/status", token=fT)
    ok("facilitator status: table override off wins over the assembly's normal", fs["ai_facilitator"]["level"] == "off" and fs["ai_facilitator"]["assembly_level"] == "normal", json.dumps(fs["ai_facilitator"]))
    code, back = org("POST", f"/api/v1/assemblies/{aid}/tables/1/facilitation", {"level": "default"})
    ok("back to the assembly's level", code == 200 and back["level"] == "normal", json.dumps(back))
    code, log_ = org("GET", f"/api/v1/rounds/{rid}/interventions")
    ok("interventions log readable (empty)", code == 200 and log_ == [], str(code))
    code, _ = phone("POST", "/api/v1/public/facilitator/leave", token=fT)
    ok("facilitator leaves", code == 200, str(code))
    code, _ = phone("GET", "/api/v1/public/facilitator/status", token=fT)
    ok("left session is refused (401)", code == 401, str(code))

    # 9. publish → the participant's page shows the report; validation after publication
    code, v0 = phone("POST", "/api/v1/public/participant/validate", {"round_id": rid, "verdict": "LOOKS_RIGHT"}, token=pT)
    ok("validation refused before publication (409)", code == 409, str(code))
    code, pub = org("POST", f"/api/v1/assemblies/{aid}/report/publish")
    ok("report published", code == 200, str(code))
    code, ps = phone("GET", "/api/v1/public/participant/status", token=pT)
    ok("participant page: report available", ps["report_available"] is True, json.dumps(ps)[:200])
    code, rep = phone("GET", "/api/v1/public/participant/report", token=pT)
    ok("participant reads the report", code == 200 and rep["assembly"]["name"] == "SMOKE 0.7b consent", str(code))
    code, v1 = phone("POST", "/api/v1/public/participant/validate", {"round_id": rid, "verdict": "MISSING", "note": "Mancava il tema dei bus"}, token=pT)
    ok("Giulia flags something missing", code == 200 and v1["verdict"] == "MISSING", json.dumps(v1))
    code, ps = phone("GET", "/api/v1/public/participant/status", token=pT)
    ok("her status lists the validation", (ps.get("validations") or {}).get(rid, {}).get("verdict") == "MISSING", json.dumps(ps.get("validations")))
    code, orep = org("GET", f"/api/v1/assemblies/{aid}/report?include_drafts=true")
    tables = [t for r in orep["rounds"] for t in r["tables"] if t.get("validations")]
    ok("organizer report shows the flag with its note", tables and tables[0]["validations"]["missing"] == 1 and "bus" in " ".join(tables[0]["validations"].get("notes", [])), json.dumps(tables)[:300])
    ok("report headings say Sessione N", orep["rounds"][0]["heading"].startswith("Sessione 1"), orep["rounds"][0]["heading"])
    ok("table 2's quotations are withheld (Giulia declined the quotations box)",
       tables[0]["table_number"] == 2 and tables[0].get("quotations_withheld") is True
       and "citazioni" in orep["methodology_note"], json.dumps({k: tables[0].get(k) for k in ("table_number", "quotations_withheld")}))
    code, mdtxt = org("GET", f"/api/v1/assemblies/{aid}/report.md", raw=True)
    ok("Markdown report prints the withholding sentence under the table",
       code == 200 and "Le citazioni di questo tavolo non sono incluse" in mdtxt.decode(errors="replace"), str(code))
    code, files = org("GET", f"/api/v1/assemblies/{aid}/files")
    ok("files listing carries the coverage field", code == 200 and all("coverage" in e for r in files["rounds"] for e in r["tables"]), str(code))

    # 10. live captions on the configured engine: two phones, a takeover, lines after it
    if not ARGS.no_captions:
        code, settings_ = org("GET", "/api/v1/admin/providers")
        engine = settings_["stt"]["provider"] if settings_["stt"]["live_enabled"] else ""
        ok("live captions are enabled on the dev instance", bool(engine), json.dumps(settings_["stt"].get("provider")))
        code, sess = org("POST", "/api/v1/sessions", {"question": "Prova sottotitoli", "table_count": 1, "duration_minutes": 10, "recording_mode": "independent", "language": "it"})
        ok("captions Session created", code == 201, str(code))
        caid, crid = sess["container_id"], sess["session_id"]
        code, pa = phone("POST", "/api/v1/public/join", {"token": tok(sess["invites"][0]["url"])})
        code, card = phone("POST", "/api/v1/public/recorder/capabilities", {"purpose": "ADD_RECORDER_TO_TABLE"}, token=pa["session_token"])
        code, pb = phone("POST", "/api/v1/public/join", {"token": tok(card["url"])})
        ok("two phones at the captions table", pb.get("joined", {}).get("slot") == 2, json.dumps(pb.get("joined")))
        chunks_a = phone_chunks(3, offset_minutes=2)
        chunks_b = phone_chunks(3, offset_minutes=2)
        code, ra = phone("POST", "/api/v1/public/recorder/start", {"round_id": crid, "mime_type": "audio/webm;codecs=opus"}, token=pa["session_token"])
        code, rb = phone("POST", "/api/v1/public/recorder/start", {"round_id": crid, "mime_type": "audio/webm;codecs=opus"}, token=pb["session_token"])
        ok("both recording; A is the live source", ra.get("live_source") is True and rb.get("live_source") is False, json.dumps({"a": ra.get("live_source"), "b": rb.get("live_source")}))
        t0 = time.monotonic()
        takeover_at = 9  # chunk index: after ~90 s A hands the captions to B
        first_line_after = None
        for seq in range(len(chunks_a)):
            due = t0 + seq * 10
            if (d := due - time.monotonic()) > 0:
                time.sleep(d)
            ca, _ = phone_raw(f"/api/v1/public/recorder/recordings/{ra['recording_id']}/chunks/{seq}", chunks_a[seq], pa["session_token"])
            cb, _ = phone_raw(f"/api/v1/public/recorder/recordings/{rb['recording_id']}/chunks/{seq}", chunks_b[seq], pb["session_token"])
            if ca != 200 or cb != 200:
                ok(f"chunk {seq} accepted from both phones", False, f"{ca}/{cb}")
            if seq == takeover_at:
                code, took = phone("POST", "/api/v1/public/recorder/live-source", {"recording_id": rb["recording_id"]}, token=pb["session_token"])
                ok("B takes over the live captions", code == 200 and took["live_source"] is True, json.dumps(took))
                taken_at = time.monotonic()
            if seq > takeover_at and first_line_after is None:
                code, live = phone("GET", f"/api/v1/public/recorder/recordings/{rb['recording_id']}/live", token=pb["session_token"])
                if live.get("lines"):
                    first_line_after = time.monotonic() - taken_at
        code, live_b = phone("GET", f"/api/v1/public/recorder/recordings/{rb['recording_id']}/live", token=pb["session_token"])
        code, live_a = phone("GET", f"/api/v1/public/recorder/recordings/{ra['recording_id']}/live", token=pa["session_token"])
        ok(f"captions flow on B after the takeover ({engine}; first line after {first_line_after and round(first_line_after)} s)",
           bool(live_b.get("lines")) and live_b.get("active") is True, json.dumps({"lines": len(live_b.get("lines") or []), "reason": live_b.get("reason")}))
        ok("A is told it is the backup", live_a.get("reason") == "backup", json.dumps(live_a)[:160])
        for rec, tk, n in ((ra, pa, len(chunks_a)), (rb, pb, len(chunks_b))):
            phone("POST", f"/api/v1/public/recorder/recordings/{rec['recording_id']}/complete", {"total_chunks": n}, token=tk["session_token"])
        STEPS.append(f"INFO captions segment: {len(chunks_a)} chunks per phone, engine={engine}")
finally:
    if aid:
        code, _ = org("DELETE", f"/api/v1/assemblies/{aid}")
        STEPS.append(f"{'PASS' if code == 204 else 'WARN'} cleanup: smoke assembly deleted ({code})")
    if caid:
        code, _ = org("DELETE", f"/api/v1/assemblies/{caid}")
        STEPS.append(f"{'PASS' if code == 204 else 'WARN'} cleanup: captions Session deleted ({code})")
    print("\n".join(STEPS))
print("ALL PASS")
