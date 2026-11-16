# Roadmap and open questions

This page lists what the bridge does not do yet, so that you do not plan around it. Nothing on this page is built.

## Results back into Citizens

The bridge is one way. Polis results do not reach Citizens: an organizer reads the Polis report in the browser. The plan is a route
on the Polis side, `GET /api/v3/citizens/results/{conversation_id}`, that returns the results of an assembly's conversation in a
documented JSON, and a `PULL_POLIS` job on the Citizens side that fetches it. The Polis results would then go into the Citizens PDF
as one unified report. There will be no Polis-side PDF.

The results should contain the consensus statements, the group-informed statements and the participation counts. The format and
timing are open, and so is the result-import format Citizens will accept. The route name is a plan, not a contract.

Polis holds no table information and votes are never linked to a table, so a per-table breakdown of Polis results is not possible.

## Participant codes

Voting is open to anyone with the link. The upstream API accepts an `xid` on a comment, but no feature of this fork uses it, and
participant codes (the `xid` whitelist) are not supported.

## Open questions

* Database backups for polis.democracyroutes.com: a nightly `pg_dump` into the `backups` volume plus a copy off the host, with
  retention to decide. See [Deployment](../polis/deployment.md#backups).
* Whether Citizens should let the organizer choose `strict_moderation`. Citizens sends a description and no `strict_moderation`.
* Polis as a Nextcloud ExApp. Two candidates are noted: a thin ExApp that uses the Democracy Routes Polis by default (one click,
  data on our servers), or an all-in-one Polis ExApp (one click, data in the organization's Nextcloud). The all-in-one version
  needs the clients patched for the AppAPI path prefix, a one-container build and a check that the participant cookie survives the
  proxy. It is also open whether this is a separate ExApp or a section of the Citizens ExApp.
* Whether the Polis notice covers voting, since votes can reveal political opinions.
* The operator fields of the Polis legal pages that the operator fills in: address, hosting country, authority, retention and
  governing law.

## Settled

The Polis statement length limit is 140 characters as a target and 400 as the hard limit. Citizens pushes directly, with the import
call.
