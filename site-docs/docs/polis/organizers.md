# Running a conversation

How a team member uses the organizer pages of a Polis instance. The organizer pages are English only. The Citizens route
(statements arriving from an assembly) is described in [Citizens + Polis](../bridge/index.md); this page covers everything that
happens on the Polis side.

## Team accounts

There is **no public sign-up**: the production nginx site answers 403 on `POST /api/v3/auth/new` and redirects `/createuser` to
the sign-in page. Accounts are created by the operator on the host:

```sh
./deploy/prod/create-account.sh        # asks for name, e-mail and password
./deploy/prod/reset-password.sh        # sets a new password
```

Polis cannot send e-mail by design (outgoing mail is off), so the admin page's reset form cannot work; the operator changes the
password with the script. Accounts store `md5(e-mail, trimmed and lowercased)@dummy.net`, never the address itself, and the
sign-in form hashes the same way, so capitals and spaces around the address do not matter. Details are in
[Deployment](deployment.md#team-accounts-and-api-keys).

## The organizer pages

Sign in at `/signin`. One top bar gives **Conversations**, **Account** and **Sign out**. The conversation list shows one card per
conversation with its status, participant count and links to its three sections. Each conversation has:

| Section | Contents |
|---|---|
| **Set up** | Title, description, open or closed, seed statements (by hand, CSV or AI), what participants can do, moderation and login rules, the home-page switch, and **Delete** at the bottom |
| **Moderate** | The three queues: to review, accepted, rejected, as pills with counts |
| **Results** | The public link with a copy button, live numbers and the report link |

The older `/m/<id>/share`, `/stats` and `/reports` addresses open Results.

## Seed statements by hand

In **Set up**, the **seed comments** box takes statements one per line, up to 400 characters each. This is also where statements
exported from Citizens can be pasted when the instance is not connected to it.

## CSV upload

The same section accepts a CSV file, sent to `POST /api/v3/comments-bulk`. The first row must be one of these headers (column
order does not matter, and a trailing empty column, as spreadsheets write, is ignored):

| Header | Meaning |
|---|---|
| `comment_text` | Upstream Polis format |
| `comment_text,original_id` | Upstream; `original_id` is ignored |
| `statement` | A bare list |
| `position,statement` | The format Citizens exports; rows are sorted by `position` when every row has one |

Each row is added as a seed one at a time. A row can come back `success`, `skipped` (empty, over 400 characters, or a duplicate of an
existing statement) or `error`. An unrecognised header is refused with `polis_err_csv_header`, a file that is not valid CSV with
`polis_err_csv_malformed`. Only a moderator of the conversation may upload.

## AI drafting

**Draft statements with AI** in Set up asks a language model for seed statements. It is **off until the operator configures a
provider** (see [Configuration](configuration.md#ai-statement-drafting)); while it is off, the draft route answers 404 `polis_err_ai_not_configured`.

What happens:

1. You describe the subject in your own words (the **request**). The conversation's title and description are only background,
   so drafts do not drift towards the title.
2. You choose how many statements you want (1 to 40) and, optionally, a language and an extra instruction.
3. The server asks the provider and shows you a list. **Nothing is stored** by the server at this point.
4. You review and edit the list, can **refine** it (the statements you kept are sent back), and add the ones you want through the
   CSV route.

What is sent to the provider: your request, the conversation's title and description, and, on a refinement, the statements you
kept. **Never** participants' statements or votes. Each organizer has a budget of 30 drafts per hour. The privacy page names the
provider in use. See [Privacy](privacy.md).

## Show on the home page

The **Appear on the home page of this site** switch in Set up lists an open conversation on `/home`. It is off by default. See
[Concepts](concepts.md#listed-conversations).

## The voting page on phones

On a phone (body width up to 600 px) opened directly, not inside an iframe, the voting page runs in **app mode**:

* the topic on one line, a bottom tab bar (**Vote**, **Write**, **Groups**, **Info**) and no page scrolling;
* the statement card fills the screen; long statements scroll inside it;
* **swipe right to agree, left to disagree**; the Disagree button is on the left and the Agree button on the right, like the
  swipe. The buttons work too and send the card off the same way;
* while dragging, the card tilts, tints and shows an Agree or Disagree stamp; two decorative slivers under it make a deck;
* on every page load the first statement runs a short hint showing both ways to vote;
* the next statement is not prefetched.

Tablets, laptops and embedded pages keep the classic layout, because the host page controls an iframe's height. After the last
statement, the **Back to the start** button goes to `P_HOME_URL` (default `/home`).

## The report

`/report/<id>`, linked from Results. On phones it shows a **summary first** (strongest consensus, most divisive statement, groups,
uncertainty), then one section per screen: swipe sideways or use the icon nav. Statement rows show the overall bar and open the
per-group bars on tap; the opinion map zooms with a pinch, drag and double-tap. Laptops keep a single-page layout. There is a
colour-blind switch and a print layout. The report is in English and Italian (browser language, or `?lang=it`).

!!! note "No Polis-side PDF"
    The report is a web page. Producing a PDF is not part of Polis; for assemblies, the plan is one unified report in Citizens (see
    the [roadmap](../bridge/roadmap.md)).

## Closing a conversation

Set the conversation to closed in Set up. Closing stops new votes; the sources describe it as the organizer's action
("the operator may close a conversation, which stops new votes, or delete it"). Deleting is at the bottom of Set up. Closing is
done on Polis: Citizens can publish the voting link on its phones and withdraw it, but cannot close the conversation.
