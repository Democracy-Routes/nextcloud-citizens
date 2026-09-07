<!--
  SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
  SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Release readiness

Reconciliation of the 52-point external beta audit against what is actually in
the repository, as of **2026-08-29**, commit `b974eb5`.

Each item is **Done** (with the commit that did it), a **Real gap** (should be
closed, is not), or **Not now** (a deliberate deferral, with the reason). The
point of writing it this way is that the audit itself could not tell the
difference — it summarised the repository's own documentation, so four of its
items described work that had already shipped, and its priorities did not match
what actually blocks a beta.

## Verdict

**Not ready for external beta.** Four blockers, all in the same place: nothing
has ever been published or installed the way an external administrator would
install it.

| Blocker | State |
|---|---|
| Signing certificate | No PR opened at `nextcloud/app-certificate-requests`. CSR exists at `/root/.nextcloud/certificates/citizens.csr`. Merging takes hours to days and gates everything below. |
| Published container image | Zero packages published. `ghcr.io/democracy-routes/citizens` does not exist yet. |
| Store-install path | Never exercised. Audit §21/§45 are not *untested* — they are impossible until an image exists. |
| Backup of `citizens_data` | Every recording, transcript and finding is on one disk, in one copy, on the development host. |

Nothing on that list is a code defect, and none of it is difficult. It is
sequencing: the certificate has to be requested before anything else can move.

## What the audit was right about

Its §40 was its best item and I had missed it. `appinfo/info.xml` — which *is*
the App Store listing — still said automatic retention and the participant
information screen were "still to come" when both had shipped in v0.6.0-beta.6.
The public description understated the app and misstated its privacy posture.
Fixed in `61f5e8a`.

## What the audit was wrong about

It read the documentation rather than the code, so it re-proposed finished work:
§14 (per-token rate limit), §16 (download cache), §17 (static-asset cache) and
§18 (the transaction guard) were all already shipped, one of them in a commit
made the same morning. Working the list top-to-bottom would have redone them.

It also missed priority entirely. Its §21, §44 and §45 — the four blockers above
— sit at the bottom of a 52-item list, behind accessibility passes and
trademark research.

## What neither of us had, and the tests found

Two real defects surfaced while closing the audit's two genuinely valuable test
items (§6 and §11). Both were invisible to the existing suite, and neither
appears anywhere in the audit:

* **Ten tables uploading at once froze the entire server** (`b974eb5`). The
  chunk-upload handler is the app's only `async def` route, so its blocking
  database and filesystem work ran on the event loop. Measured: two of ten
  uploads completed in 600 s, at 61 s each; a redirect touching no database took
  26.7 s and then timed out. After the fix: 10/10 in 34.5 s, nothing over 1.7 s,
  that same redirect at 176 ms. The old load test could not see it because it
  ran ten devices in ten *separate* assemblies, which contend for nothing.
* **"Revoke access" left phones connected** (`4a9a23d`). It disconnected only
  devices holding a currently-active invite — so after any QR regeneration, the
  tables already recording were precisely the ones it skipped.

That is the argument for §6 and §11 having been worth doing, and the argument
for treating the rest of the audit's test proposals on their merits rather than
in order.

## The 52 items

### Identity, documentation, scope (§1–§4)

| # | Item | Status |
|---|---|---|
| 1 | Project identity and authorship | **Done** — `61f5e8a`: moved to `Democracy-Routes`, Alessandro Oppo as maintainer, Philip as contributor. Existing SPDX headers deliberately unchanged. |
| 2 | Documentation consistency | **Done** — `61f5e8a`. No "still to come" claim survives in `README.md`, `info.xml` or `docs/`. |
| 3 | Freeze V1 scope | **Done** — no product feature has been added since; every commit below is a fix, a test or metadata. |
| 4 | Run the full test suite | **Done** — 375 Python and 205 frontend tests pass, plus 5 browser tests in the separate pre-release suite; lint clean, store schema validation passes. |

### Testing (§5–§11)

| # | Item | Status |
|---|---|---|
| 5 | Browser E2E A–E | **Mostly done** — `d6cff15`. Five specs drive the real recorder in Firefox: A and C (network loss, reload recovery), plus a phone dying mid-round, a disconnected phone's backlog, and clearing the phones. `offline.spec.ts` had also been silently broken since the consent screen landed — it never reached the recorder. B, D and E remain unwritten. |
| 6 | Replace the 10-device test | **Done** — `b974eb5`, `tests/load/load_g_single_assembly.py`. Found the event-loop freeze. |
| 7 | Long-duration stress test | **Not now** — 1800 chunks over 30 minutes needs care on a host with ~1.9 GB available; it would measure the host, not the app. |
| 8 | Fault-injection test | **Real gap** — worth doing, nobody has. |
| 9 | Real-phone checklist | **Smaller than it was** — the browser suite now covers what a browser can. What is left genuinely needs hardware: wake locks (headless browsers do not sleep), battery reporting (Firefox implements none), hard microphone denial, and iOS Safari. |
| 10 | Physical room test | **Not now** — same. |
| 11 | Recorder security audit | **Done** — `4a9a23d`, `tests/integration/test_recorder_isolation.py`: nine negative-authorization tests. Found the revoke gap. |

### Security (§12–§18, §26)

| # | Item | Status |
|---|---|---|
| 12 | QR-token security | **Done** — tokens stored as SHA-256, raw copy encrypted with the app secret, 30-day expiry (`0013`), token travels in the URL fragment so it never reaches access logs. |
| 13 | API-key security | **Done** — keys held in Nextcloud appconfig marked sensitive; `tests/unit/test_logging_redaction.py` guards the log path. |
| 14 | Public-route rate limits | **Done** (before the audit) — `b3ab7af`. Per-token, not per-IP: keying on IP rejected table 11 at a venue behind one NAT. |
| 15 | Nextcloud authorization | **Done** — `05c766b` fixed admin detection via `/ocs/v1.php/cloud/user`; verified live against an admin and a non-admin account. |
| 16 | Download/cache security | **Done** (before the audit) — `9f74f8b`. |
| 17 | Static-asset cache | **Done** (before the audit) — `c6c76a6`. |
| 18 | Database concurrency | **Done** — `05c766b` (config reads out of transactions, plus an AST guard), `b974eb5` (event loop, plus a second AST guard). This is where the worst defect was. |
| 26 | Logging/privacy | **Done** — redaction test in the suite. |

### Packaging and release (§19–§25, §40–§46)

| # | Item | Status |
|---|---|---|
| 19 | Migration audit | **Partial** — migrations 0001–0013 run from scratch in `test_storage_and_db.py`; no test upgrades an *existing* volume. |
| 20 | Persistent-volume upgrade test | **Real gap** — the failure mode that loses user data on upgrade, and it is untested. Worth more than most of this list. |
| 21 | Clean Docker-install test | **BLOCKER** — impossible until an image is published. |
| 22 | amd64 + arm64 | **Not now** — `release.yml` already builds both; arm64 has never been run. |
| 23 | Container hardening | **Real gap** — not audited. |
| 24 | Python dependency scan | **Real gap** — no scanning in CI. |
| 25 | npm dependency scan | **Real gap** — no scanning in CI. |
| 40 | App Store metadata | **Done**, except the six screenshots date from 25 August and predate the Settings tabs, the aligned live/final columns and the QR PDF. Reshoot before submission. |
| 41 | Naming/trademark | **Not now**. |
| 42 | Release workflow safety | **Partial** — `release.yml` exists and is tag-gated; never run. |
| 43 | Version consistency | **Done** — `test_version_consistency.py` checks `info.xml`, its image tag, `pyproject.toml` and `package.json` agree. |
| 44 | First GitHub prerelease | **BLOCKER** — no tags, no releases. |
| 45 | Install prerelease on a clean instance | **BLOCKER** — depends on 44. Must run on a throwaway instance: `docker-install` against the live one would replace its working manual registration and point it at an empty volume. |
| 46 | Upgrade test A → B | **BLOCKER** — depends on 44. |

### Providers, AI, reports (§27–§39)

| # | Item | Status |
|---|---|---|
| 27 | Disk-full test | **Real gap** — `/api/v1/health` reports free disk, but the behaviour when it runs out is untested. |
| 28 | Retention audit | **Done** — `e499c96`, migration `0012`, instance default with per-assembly override, audit-logged, audio only. |
| 29 | Provider matrix | **Partial** — four engines implemented and unit-tested; the matrix has never been run against live providers. |
| 30 | Mistral real-provider test | **Not now** — costs money and a rotated key; belongs with §9/§10. |
| 31 | Deepgram real-provider test | **Not now** — same. |
| 32 | Evidence integrity | **Done** — `e499c96`; every finding carries the passage supporting it. |
| 33 | Adversarial prompt/schema tests | **Real gap**. |
| 34 | AI output language test | **Real gap** — the app supports five languages and nothing checks the model answers in the right one. |
| 35 | Human-review integrity | **Done** — approve/reject works (`ea0c98b` fixed the 405 that broke it). |
| 36 | Report integrity | **Done**. |
| 37 | Report wording audit | **Real gap** — includes one unresolved report: a PDF from the admin panel showed references where the phone's copy did not. Not reproduced. |
| 38 | Accessibility audit | **Not now**. |
| 39 | Mobile UX audit | **Not now**. |

### Process (§47–§52)

| # | Item | Status |
|---|---|---|
| 47 | Pilot deployment checklist | **Real gap** — write it before the first real assembly. |
| 48 | Known limitations document | **Real gap** — partly covered by `info.xml`'s status section, which is honest about the information screen not being a per-individual consent record. |
| 49 | Supported scale for beta | **Partial, with new evidence** — 10 tables in one assembly now verified end to end: 34.5 s, no request over 1.7 s, server responsive throughout. 20 tables is claimed in the brief and remains unmeasured. |
| 50 | Final security pass | Pending — after the gaps above. |
| 51 | Final release blockers | The four in the verdict. |
| 52 | This report | **Done** — this file. |

## Next, in order

1. **Open the certificate PR.** It blocks §44–§46 and takes days of waiting on
   other people. Steps are in [releasing.md](releasing.md).
2. **Back up `citizens_data`.** Independent of everything else, and currently
   the largest single risk to work already done.
3. **Set the release secrets** on the new repo: `APP_PRIVATE_KEY`,
   `APP_PUBLIC_CRT`, `APPSTORE_TOKEN`.
4. **Tag a prerelease**, let the workflow publish, then install it on a
   throwaway instance — never the live one.
5. Then the real gaps, worst first: §20 (volume upgrade), §5 (E2E A/B/D/E),
   §24–§25 (dependency scanning), §27 (disk-full).

## Standing items

Not audit items, but outstanding:

- **Rotate the Mistral and Deepgram keys and the `citizens-test` password**
  that were pasted into a conversation. Oldest item here, still undone.
- **Decide what retention does when there is no transcript.**
  `sweep_expired_audio` deletes a recording on the retention timer without
  checking whether anything was ever written down from it — so a failed
  transcription plus an expiry means the assembly is gone, silently, on a
  timer. The choice is whether retention refuses to delete or deletes loudly;
  it is the only remaining defect that can lose an assembly outright.
- **Translate the organizer interface.** The citizens' half is done and
  guarded; the organizer's is still English. The mechanism, catalogues and
  parity test all exist, so this is extraction rather than design — point the
  untranslated-strings guard at `frontend/src/components/` when it happens.
- Reshoot the six screenshots.
