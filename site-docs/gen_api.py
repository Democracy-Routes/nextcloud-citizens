#!/usr/bin/env python3
"""Turn _generated/openapi.json into Markdown pages under docs/reference/api/.

Standard library only. The app's OpenAPI document carries no tags, so the
operations are grouped by the first path segment after /api/v1/ (the
"public" group is the phone-facing recorder API). Run by scripts/docs-build.sh.
"""
import html
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "_generated" / "openapi.json"
OUT = HERE / "docs" / "reference" / "api"

# group key -> (page file, title, intro)
GROUPS = {
    "assemblies": ("assemblies.md", "Assemblies",
                   "Assemblies, their settings, participants, tables, consent, files, report, "
                   "seeds and everything else scoped to one assembly. Organizer routes."),
    "rounds": ("rounds.md", "Rounds (sessions)",
               "A Session is a Round in the schema: these routes start and end it, monitor it, "
               "and hold its findings, analysis and messages. Organizer routes."),
    "recordings": ("recordings.md", "Recordings",
                   "Operations on one recording: transcripts, audio, retranscription, "
                   "handover and promotion. Organizer routes."),
    "sessions": ("sessions.md", "Sessions",
                 "Create and list Sessions (including Record now). Organizer routes."),
    "uploads": ("uploads.md", "Uploads",
                "Resumable uploads in parts, used by session import and by attaching audio "
                "or a transcript. Organizer routes."),
    "admin": ("admin.md", "Administration",
              "Settings, provider tests, Vosk models and instance status. Administrator routes."),
    "public": ("recorder.md", "Recorder and participant (public)",
               "The routes phones and participants call, authenticated by the bearer token "
               "of their session rather than by an organizer sign-in."),
    "auth": ("auth.md", "Accounts (standalone)",
             "Sign-in, invitations and password reset in standalone mode."),
    "other": ("other.md", "Other",
              "Health, findings, participants, help requests and the static entry points."),
}
ORDER = list(GROUPS)


def group_of(path: str) -> str:
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 3 and parts[0] == "api" and parts[1] == "v1":
        return parts[2] if parts[2] in GROUPS else "other"
    return "other"


def esc(text: str) -> str:
    """Escape HTML outside code spans; neutralise table-breaking characters."""
    pieces = re.split(r"(`[^`]*`)", text)
    return "".join(p if p.startswith("`") else html.escape(p, quote=False) for p in pieces)


def cell(text: str) -> str:
    return esc(" ".join(str(text).split())).replace("|", "\\|")


class Resolver:
    def __init__(self, doc):
        self.doc = doc

    def ref(self, ref):
        node = self.doc
        for part in ref.lstrip("#/").split("/"):
            node = node[part]
        return node

    def type_of(self, schema) -> str:
        if not schema:
            return "any"
        if "$ref" in schema:
            return schema["$ref"].split("/")[-1]
        for key in ("anyOf", "oneOf"):
            if key in schema:
                return " or ".join(self.type_of(s) for s in schema[key])
        if "allOf" in schema:
            return " + ".join(self.type_of(s) for s in schema["allOf"])
        t = schema.get("type", "any")
        if t == "array":
            return f"array of {self.type_of(schema.get('items'))}"
        if "enum" in schema:
            return t + " (" + ", ".join(f"`{e}`" for e in schema["enum"]) + ")"
        if t == "string" and schema.get("format"):
            return f"string ({schema['format']})"
        return t

    def model(self, schema):
        """Return the object schema behind a request body, or None."""
        if not schema:
            return None
        if "$ref" in schema:
            return self.model(self.ref(schema["$ref"]))
        for key in ("anyOf", "oneOf"):
            if key in schema:
                for s in schema[key]:
                    m = self.model(s)
                    if m:
                        return m
        if schema.get("type") == "object" and schema.get("properties"):
            return schema
        return None


def render_op(res: Resolver, method: str, path: str, op: dict) -> list[str]:
    out = [f"### `{method.upper()}` `{path}`", ""]
    summary = op.get("summary")
    if summary:
        out += [f"**{cell(summary)}**", ""]
    desc = (op.get("description") or "").strip()
    if desc:
        out += [esc(desc), ""]
    if op.get("deprecated"):
        out += ['!!! warning "Deprecated"', "    This operation is marked deprecated.", ""]

    params = op.get("parameters") or []
    if params:
        out += ["**Parameters**", "", "| Name | In | Type | Required | Description |",
                "|---|---|---|---|---|"]
        for p in params:
            req = "yes" if p.get("required") else "no"
            out.append(f"| `{p['name']}` | {p['in']} | {cell(res.type_of(p.get('schema')))} | "
                       f"{req} | {cell(p.get('description', ''))} |")
        out.append("")

    body = op.get("requestBody")
    if body:
        content = body.get("content", {})
        for ctype, media in content.items():
            schema = media.get("schema")
            required = "required" if body.get("required") else "optional"
            out += [f"**Request body** (`{ctype}`, {required})", ""]
            m = res.model(schema)
            if m:
                reqs = set(m.get("required", []))
                out += ["| Field | Type | Required | Description |", "|---|---|---|---|"]
                for name, prop in m["properties"].items():
                    out.append(f"| `{name}` | {cell(res.type_of(prop))} | "
                               f"{'yes' if name in reqs else 'no'} | "
                               f"{cell(prop.get('description') or prop.get('title') or '')} |")
                out.append("")
            else:
                out += [f"Type: {cell(res.type_of(schema))}", ""]

    resp = op.get("responses") or {}
    if resp:
        out += ["**Responses**", "", "| Code | Meaning | Body |", "|---|---|---|"]
        for code, r in resp.items():
            body_types = []
            for ctype, media in (r.get("content") or {}).items():
                body_types.append(f"`{ctype}`: {res.type_of(media.get('schema'))}")
            out.append(f"| {code} | {cell(r.get('description', ''))} | {cell('; '.join(body_types)) or '-'} |")
        out.append("")
    return out


def main() -> int:
    if not SRC.exists():
        print(f"missing {SRC}: generate the OpenAPI document first (see scripts/docs-build.sh)",
              file=sys.stderr)
        return 1
    doc = json.loads(SRC.read_text())
    res = Resolver(doc)
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.md"):
        old.unlink()

    buckets: dict[str, list] = {k: [] for k in GROUPS}
    for path, item in doc["paths"].items():
        for method, op in item.items():
            if method not in ("get", "post", "put", "delete", "patch", "head", "options"):
                continue
            buckets[group_of(path)].append((path, method, op))

    version = doc.get("info", {}).get("version", "")
    total = sum(len(v) for v in buckets.values())
    index = [
        "# API reference", "",
        "Generated from the application's own OpenAPI document "
        f"(app version `{version}`, {total} operations). Do not edit these pages by hand: "
        "rebuild them with `sh scripts/docs-build.sh`.", "",
        "All organizer routes live under `/api/v1/`. In Nextcloud mode they are reached through "
        "the AppAPI proxy at `/index.php/apps/app_api/proxy/citizens/api/v1/...` with a "
        "Nextcloud session; in standalone mode they are served at `/api/v1/...` with the "
        "sign-in cookie. There is no API token for external services; see "
        "[Polis bridge contract](../../bridge/contract.md) for how the one external integration works.", "",
        '!!! note "Verbs"',
        "    The AppAPI proxy forwards only GET, POST, PUT and DELETE. Partial updates therefore "
        "use PUT; the application has no PATCH routes.", "",
        "| Group | Operations | What it holds |", "|---|---|---|",
    ]
    for key in ORDER:
        fname, title, intro = GROUPS[key]
        index.append(f"| [{title}]({fname}) | {len(buckets[key])} | {cell(intro)} |")
    index.append("")
    (OUT / "index.md").write_text("\n".join(index))

    for key in ORDER:
        fname, title, intro = GROUPS[key]
        lines = [f"# {title}", "", intro, "",
                 f"{len(buckets[key])} operations. Generated; do not edit.", ""]
        for path, method, op in sorted(buckets[key], key=lambda t: (t[0], t[1])):
            lines += render_op(res, method, path, op)
        (OUT / fname).write_text("\n".join(lines))
    print(f"api pages written: {len(ORDER) + 1}, operations: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
