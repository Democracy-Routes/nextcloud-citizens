# Privacy

What a Polis installation stores, what leaves the server, and what the operator must still do. This is condensed from the built-in
privacy notice (`client-admin/src/content/privacy.md`), `docs/production.md` and `docs/decisions.md`. The built-in pages are a
description of the software, **not legal advice**; have them reviewed. For what crosses from Citizens, see
[Privacy across the bridge](../bridge/privacy.md).

## What is stored

**For a participant** (votes or writes a statement):

* A random identifier in a cookie (`pc`, one year), so votes are counted once and statements are not repeated. Not linked to a name;
  no name is asked.
* Each vote (agree, disagree, pass) per statement, with the time.
* Statements the participant writes, with the time. They are public.
* The address of the page the conversation was opened from, when embedded.
* No location: the software can look one up from a network address, but that is off.

**For an organizer account:**

* A display name, a password hash, and a one-way hash of the e-mail address (`md5(e-mail)@dummy.net`). The address itself is never
  stored and Polis sends no e-mail.
* The conversations the account creates: title, description, settings, statements.

**Server logs:** the web server logs the network address, time and page of each request, for security and troubleshooting; they
follow the operator's log rotation.

**Cookies:** only functional ones: `pc` (participant), `token2`, `uid2`, `e`, `uc` (organizer session), `ct`, `tryCookie` (a cookie
test needed when embedded). No consent banner, because nothing optional is set.

**Participant codes (xids).** The upstream API accepts an `xid` (an external participant id) on comments. Citizens-side
**participant codes are deferred**; the sources of this fork describe no xid feature, so none is documented here. See the
[roadmap](../bridge/roadmap.md).

## What leaves the server

Nothing by default. No script, font or image is loaded from another company (fonts are self-hosted), there are no analytics, and no
e-mail. The only outbound call is **AI drafting**, and only when the operator configures a provider: it sends the organizer's request,
the conversation title and description and, on refinement, the statements the organizer kept; never participants' statements or votes.
Nothing from the provider's answer is stored. The privacy page names the provider, its region and its policy, read live from
`GET /api/v3/ai/status`; a provider outside the EU is the one exception to "no transfer outside the EU" in the built-in notice.

The stock PolisOrbis 1.5.0 images loaded d3 and Font Awesome from third-party CDNs on the report page; the fork's report loads
nothing external.

## Legal pages

`/privacy` and `/tos` are built in (English and Italian), written from what the software does, and name the operator from the
`P_OPERATOR_*` values. They state the lawful basis as the participant's consent by voting after reading the notice, and note that
votes on public issues can reveal political opinions (GDPR Art. 9). Missing operator values show as "[not set]". The runbook's own
checklist item: confirm that the notice covers voting before relying on it.

## Retention

Votes and statements are kept for as long as the conversation exists, and at most the `P_RETENTION` phrase the operator sets. The
operator may close a conversation (no new votes) or delete it. **There is no automatic deletion**: the purge is off (see
[the purge](deployment.md#the-purge-and-the-data-loss-of-2-november-2026)), so conversations stay until deleted by hand.
Because participation is anonymous, the operator can find one participant's votes only if given the value of that person's `pc`
cookie.

## For the operator

* Fill the `P_OPERATOR_*`, `P_HOSTING_COUNTRY`, `P_SUPERVISORY_AUTHORITY`, `P_RETENTION` and `P_GOVERNING_LAW` values and rebuild the
  file-server image; the pages show what is missing.
* **There are no backups**, so a restore after loss is not possible today (see [Deployment](deployment.md#backups)).
* Keep API keys out of git and chat; one key per Citizens installation.
