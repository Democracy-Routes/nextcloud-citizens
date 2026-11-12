# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rebuild the Milano session on this instance from the eumans export.

Organizer routes signed with the ExApp secret straight at the container, as
smoke07b does. Never prints transcript text. Steps:

  1. organisation name and logo (admin)  — unless --keep-branding
  2. upload the session export in parts, import it under the new name with
     table 12 folded into table 2
  3. upload the repaired transcript, attach it to table 8
  4. print the assembly id and what was queued

    python3 tests/load/rebuild_milano.py --as alex \
        --export .orca/drops/Citizen-Assembly-su-Milano-session-export.zip \
        --transcript .orca/drops/table8-transcript.json \
        --logo /path/to/eumans.png
"""

import argparse
import base64
import hashlib
import json
import pathlib
import subprocess
import urllib.error
import urllib.request

REPO = pathlib.Path("/root/NextCloud-Citizen")
SECRET = (REPO / ".app_secret").read_text().strip()
IP = subprocess.check_output(
    ["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}",
     "nc_app_citizens"],
    text=True,
).split()[0]
ORG = f"http://{IP}:23000"


def call(method, path, user, data=None, raw=None):
    headers = {
        "EX-APP-ID": "citizens", "EX-APP-VERSION": "1.0.0",
        "AUTHORIZATION-APP-API": base64.b64encode(f"{user}:{SECRET}".encode()).decode(),
    }
    body = None
    if raw is not None:
        headers["Content-Type"] = "application/octet-stream"
        body = raw
    elif data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data).encode()
    req = urllib.request.Request(ORG + path, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            payload = r.read()
            return r.status, (json.loads(payload) if payload else {})
    except urllib.error.HTTPError as exc:
        text = exc.read().decode(errors="replace")
        try:
            return exc.code, json.loads(text)
        except ValueError:
            return exc.code, {"detail": text[:300]}


def upload(user, path: pathlib.Path, kind: str) -> str:
    payload = path.read_bytes()
    status, opened = call("POST", "/api/v1/uploads", user, {
        "kind": kind, "filename": path.name, "size_bytes": len(payload),
    })
    assert status == 201, (status, opened)
    size = opened["part_bytes"]
    for index in range(opened["parts"]):
        status, body = call(
            "POST", f"/api/v1/uploads/{opened['upload_id']}/parts/{index}", user,
            raw=payload[index * size:(index + 1) * size],
        )
        assert status == 200, (status, body)
    status, done = call("POST", f"/api/v1/uploads/{opened['upload_id']}/complete", user, {
        "sha256": hashlib.sha256(payload).hexdigest(),
    })
    assert status == 200, (status, done)
    print(f"uploaded {path.name}: {len(payload)} bytes in {opened['parts']} parts")
    return opened["upload_id"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--as", dest="user", required=True, help="Nextcloud user who will own the assembly")
    ap.add_argument("--admin", default=None, help="Nextcloud admin for branding (default: same as --as)")
    ap.add_argument("--export", required=True, type=pathlib.Path)
    ap.add_argument("--transcript", required=True, type=pathlib.Path)
    ap.add_argument("--table", type=int, default=8)
    ap.add_argument("--name", default="Citizen Assembly - Milano Digital Week")
    ap.add_argument("--merge", default="12:2", help="from:into table numbers, comma-separated")
    ap.add_argument("--logo", type=pathlib.Path, default=None)
    ap.add_argument("--org", default="Eumans")
    ap.add_argument("--keep-branding", action="store_true")
    args = ap.parse_args()
    admin = args.admin or args.user

    if not args.keep_branding:
        status, body = call("PUT", "/api/v1/admin/providers", admin, {"organization_name": args.org})
        print("organisation name:", status, body if status != 200 else args.org)
        if args.logo is not None:
            status, body = call("PUT", "/api/v1/admin/logo", admin, {
                "data": base64.b64encode(args.logo.read_bytes()).decode(),
            })
            print("logo:", status, body if status != 204 else "set")

    export_id = upload(args.user, args.export, "session_export")
    merges = [
        {"from": int(a), "into": int(b)}
        for a, b in (pair.split(":") for pair in args.merge.split(",") if pair)
    ]
    status, result = call("POST", "/api/v1/assemblies/import", args.user, {
        "upload_id": export_id, "name": args.name, "merge_tables": merges,
    })
    print("import:", status, json.dumps(result, ensure_ascii=False))
    assert status == 201, result
    assembly_id = result["assembly_id"]

    status, listing = call("GET", f"/api/v1/assemblies/{assembly_id}/files", args.user)
    assert status == 200, listing
    targets = [
        e for r in listing["rounds"] for e in r["tables"]
        if e["table_number"] == args.table and not e["has_transcript"]
    ]
    assert len(targets) == 1, f"table {args.table}: expected one recording without a transcript: {targets}"
    recording_id = targets[0]["recording_id"]
    transcript_id = upload(args.user, args.transcript, "transcript")
    status, attached = call("POST", f"/api/v1/recordings/{recording_id}/transcript", args.user, {
        "upload_id": transcript_id,
    })
    print("attach:", status, json.dumps(attached))
    assert status == 200, attached

    status, listing = call("GET", f"/api/v1/assemblies/{assembly_id}/files", args.user)
    for r in listing["rounds"]:
        for e in r["tables"]:
            print(f"  table {e['table_number']:>2}  {e['state']:<18} transcript={e['has_transcript']}")
    print("assembly:", assembly_id)


if __name__ == "__main__":
    main()
