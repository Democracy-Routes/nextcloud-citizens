# Polis consultation

An assembly produces findings. A [Polis](https://pol.is) conversation needs short statements
that strangers can agree or disagree with. **Polis seeds** are those statements, written by the
analysis model from your *approved* findings and reviewed by you before anything leaves Citizens.
It works the same in Nextcloud and in standalone mode.

## Before you start

* AI analysis is configured (an analysis key in Settings).
* The assembly's findings have been reviewed, and the ones you stand behind are **approved** in
  the Analysis tab. Only approved findings are used.
* To send straight to Polis: an administrator has set the instance URL and API key in
  Settings, AI, Polis (see [Settings reference](../admin/settings.md#polis)). The target is the
  Citizens-Polis fork, which has the import endpoint described in the
  [Polis bridge contract](../reference/polis-contract.md).

## The workflow

1. Open the assembly, go to **Results, Polis seeds**, choose how many statements you want on the
   slider (10 to 60; the panel recommends a number from the approved findings and shows about how
   long the vote will take at eight seconds a statement) and press **Generate**. The statements
   are written in the assembly's language by the three passes below.
2. Read every statement. You can **edit** it (a counter shows the length), **approve** it,
   **reject** it, **delete** it, or **add** your own by hand.
3. Drag statements into the order you want them to appear. Hand-written ones count as reviewed.
4. When every statement is approved or rejected, **Export** and **Send to Polis** become
   available. In a hurry, **Approve all** approves every draft in one go; rejected statements stay
   rejected, and you can still edit or reject any statement afterwards.

## How the statements are written

Three passes, so that each statement rests on something people actually said.

1. **Ground.** For each approved finding the model reads the finding and the transcript excerpts it
   cites, and lists the concrete claims people made.
2. **Draft.** One statement per claim, written to a style card: one idea, declarative, neutral,
   a concrete actor and object.
3. **Critique.** A second pass scores every draft on four points (grounded, contestable, one idea,
   clear; 0 to 2 each), rewrites the ones that can be mended and drops the ones that cannot.

The statements are then selected breadth-first across findings: the findings most tables raised
first, one statement each, then second statements while the budget lasts.

### The Why panel

Each statement has a **Why** button. It opens the trail: the finding it was written from, the
**claim**, the transcript **excerpt** it rests on (names masked) and the four **scores**. Nothing in
it is editable. A statement the critic scored 0 on any point carries a "Low score" badge in the list
so you can check it first. Statements you wrote by hand, or that older runs produced, have no trail.

!!! warning "The excerpt is for you only"
    The excerpt in the Why panel never goes to Polis and is not part of any export.

## What makes a good statement

* One idea only, declarative, neutral voice.
* It names who should do what, concretely: an actor, an action and an object taken from the finding.
* The dissent test: a reasonable person could disagree with it.
* No empty verbs ("promote", "value", "support") without a concrete object.
* A disagreement or a trade-off is two statements, one per side.
* No names, no table numbers, no quotations, no "our table".
* Under 140 characters. The hard limit is 400, the size of the PolisOrbis seed box; Citizens will
  not save more.

| Weak | Better |
|---|---|
| "At table 3 Maria said the council should publish the budget and also hold open meetings." | "The council should publish its budget every year in a readable form." |
| "We all think transport is bad." | "Night buses should run at least hourly." |
| "Should the city build more bike lanes?" (a question) | "The city should build more protected bike lanes." |

## Generating again

**Generate** can be pressed again, for instance after approving more findings or with a different
number on the slider. It replaces only untouched drafts. Statements you edited, approved, rejected or
wrote yourself stay as they are and count towards the number you asked for; the rest of the budget is
filled with new drafts, and near duplicates are dropped.

If the analysis is re-run and a finding is replaced, the statements written from it keep their text
but lose the link to the finding and show a **stale** badge. Check that they still say what you
mean, edit or approve them, or delete them. Editing a statement clears the badge.

## Export

Export downloads approved statements only, numbered from 1:

* `<assembly>-statements.csv`: UTF-8, header `position,statement`, quoted as RFC 4180.
* `<assembly>-statements.json`: schema `citizens.statement-seeds/1`.

Exported statements are marked **EXPORTED**; you can export again. Formats are specified in
[Seeds export formats](../reference/seeds-formats.md).

## Send to Polis

**Send to Polis** sends the approved statements to the Polis instance an administrator configured
(**Test connection** in Settings says whose key it is). Citizens sends the same file the JSON export
writes, plus the assembly name as the topic and its description. The first send creates a public
conversation and its report page; the three links (voting page, moderation, Polis report) then appear
on the seeds card. Sending again is safe: Polis finds the conversation by the assembly name and adds
only the statements whose text is new. The statements sent are marked **EXPORTED**.

If Polis refuses the send because a statement looks like personal data (an email address, a phone
number, a table reference, a verbatim quote in quotation marks), nothing is created, the refused
statements get a **Refused by Polis** badge, and you edit them and send again.

Without a configured instance the button is disabled and the export files remain the way: paste the
statements into the **seed comments** box of the Polis admin page, one per line (the CSV's second
column), or send the file to the person who runs the instance.

## Put the poll on the devices

Once the statements are on Polis, **Publish the poll on the devices** on the seeds card shows the
voting link, with a QR code, on every table phone and on the participants' own pages, the way the
report is published. People at a table scan the code on the table phone with their own phone and vote.
The Polis conversation is public, so anyone with the link can vote. The same QR is in the **QR codes**
tab, and the printable table sheet gains a page of VOTE cards once the poll is published.
**Withdraw from the devices** takes it off the phones again; the Polis conversation stays open until
its moderator closes it.

## Privacy

The files contain statement text only: no evidence, transcript, participant data or Citizens ids. They
are meant to be published, so read them as if they already were. Only the findings' text is sent to
the analysis provider to write the statements, never audio. Seeds are deleted with the assembly.

## Troubleshooting

* **"AI analysis is not configured" (409):** add an analysis API key in Settings, then press Generate
  again.
* **"Approve some findings first" (409):** approve at least one finding in the Analysis tab.
* **Export is disabled:** at least one statement is still a draft. Approve or reject it; at least one
  must be approved.
* **A "stale" badge:** its finding was replaced by a new analysis run. Review the text; editing it
  clears the badge.
* **Nothing happens after Generate:** a run is already queued or running. The panel shows the job's
  state and any failure.
