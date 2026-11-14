# Roadmap and open questions

Nothing on this page is built. It collects what the sources of both repositories mark as planned or undecided, so that no one
assumes otherwise.

## Results back into Citizens (not built)

Today the bridge is one way. Polis results do not reach Citizens: an organizer reads the Polis report in the browser.

Planned, per the Citizens plan:

* On the Polis side, `GET /api/v3/citizens/results/{conversation_id}`, returning the results of an assembly's conversation in a
  documented JSON.
* On the Citizens side, a `PULL_POLIS` job that fetches it.
* **One unified report:** the Polis results go into the Citizens PDF in a later step. There will be no Polis-side PDF.

The sources name what the results should contain: the consensus statements, the group-informed statements and the participation
counts. The **format and timing are open** (`docs/decisions.md`: "Results back into Citizens: format and timing, once Citizens
tranche 3 exists"), and so is the result-import format Citizens will accept. Until then, `docs/citizens-integration.md` lists the
requirement as "later". The planned route name is a plan, not a contract.

Because Polis holds no table information and votes are never linked to a table, any per-table breakdown of Polis results is not
possible and is not planned.

## Participant codes (deferred)

Decided on 2026-11-13: participant codes, the `xid` whitelist, are deferred. Today voting is open to anyone with the link. The upstream API accepts an `xid` on a comment; no feature of this
fork uses it.

## Open questions from the Polis repository

From `docs/decisions.md` and `docs/citizens-integration.md`:

* **Database backups** for polis.democracyroutes.com: a nightly `pg_dump` into the `backups` volume plus a copy off the host;
  retention to decide. See [Deployment](../polis/deployment.md#backups).
* **Citizens `description` and `strict_moderation`**: whether Citizens should let the organizer choose `strict_moderation`. Citizens
  currently sends a description and no `strict_moderation`.
* **Polis as a Nextcloud ExApp**, later. Two candidates are noted: a thin ExApp that uses the Democracy Routes Polis by default (one
  click, data on our servers), or an all-in-one Polis ExApp (one click, data in the organisation's Nextcloud; needs the clients
  patched for the AppAPI path prefix, a one-container build and a check that the participant cookie survives the proxy). Also open:
  whether it is a separate ExApp or a section of the Citizens ExApp.
* **Privacy coverage**: the runbook asks to confirm that the notice covers voting, since votes can reveal political opinions.
* The owner-to-fill operator fields of the Polis legal pages (address, hosting country, authority, retention, governing law).

## Already settled

* The Polis statement length limit: 140 characters as a target, 400 as the hard limit.
* Whether Citizens pushes directly: yes, with the import call.
