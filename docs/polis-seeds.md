# Polis seeds

An assembly produces findings. A Polis conversation needs short statements
that strangers can agree or disagree with. **Polis seeds** are those
statements, written by the analysis model from your *approved* findings and
reviewed by you before anything leaves Citizens. It works the same in
Nextcloud and in standalone mode.

## Before you start

* AI analysis is configured (an analysis key in Settings).
* The assembly's findings have been reviewed, and the ones you stand behind
  are **approved** in the Analysis tab. Only approved findings are used.

## The workflow

1. Open the assembly, go to **Results -> Polis seeds** and press **Generate**.
   The model writes one to three statements per approved finding, in the
   assembly's language. It takes a moment; the panel updates when it is done.
2. Read every statement. You can **edit** it (a counter shows the length),
   **approve** it, **reject** it, **delete** it, or **add** your own by hand.
3. Drag statements into the order you want them to appear. Hand-written ones
   count as reviewed.
4. When every statement is approved or rejected, **Export** becomes available.

## What makes a good statement

* One idea only, declarative, neutral voice.
* No names, no table numbers, no quotations, no "our table".
* Under 140 characters. The hard limit is 400, which is the size of the
  PolisOrbis seed box; Citizens will not save more.

| Weak | Better |
|---|---|
| "At table 3 Maria said the council should publish the budget and also hold open meetings." | "The council should publish its budget every year in a readable form." |
| "We all think transport is bad." | "Night buses should run at least hourly." |
| "Should the city build more bike lanes?" (a question) | "The city should build more protected bike lanes." |

## Generating again

**Generate** can be pressed again, for instance after approving more
findings. It replaces only untouched drafts. Statements you edited, approved,
rejected or wrote yourself stay as they are, and near duplicates are dropped.

If the analysis is re-run and a finding is replaced, the statements written
from it keep their text but lose the link to the finding and show a **stale**
badge. Check that they still say what you mean, edit or approve them, or
delete them. Editing a statement clears the badge.

## Export

Export downloads approved statements only, numbered from 1:

* `<assembly>-statements.csv` - UTF-8, header `position,statement`, quoted as
  RFC 4180.
* `<assembly>-statements.json` - schema `citizens.statement-seeds/1`, with the
  assembly name and language, the export time and the statements.

Exported statements are marked **EXPORTED**. You can export again.

## Putting them into Polis

For now this is by hand: open the Polis conversation, then paste the
statements into the **seed comments** box in its admin page, one per line (they
are in the CSV's second column). Or send the file to the person who runs the
Polis instance, who can import it. A direct push from Citizens to Polis may
come later.

## Privacy

The files contain statement text only: no evidence, transcript, participant
data or Citizens ids. They are meant to be published, so read them as if they
already were. Seeds are deleted with the assembly. See
[privacy.md](privacy.md).

## Troubleshooting

* **"AI analysis is not configured" (409)**: add an analysis API key in
  Settings, then press Generate again.
* **"Approve some findings first" (409)**: approve at least one finding in the
  Analysis tab.
* **Export is disabled**: at least one statement is still a draft. Approve or
  reject it; at least one must be approved.
* **A "stale" badge**: its finding was replaced by a new analysis run. Review
  the text; editing it clears the badge.
* **Nothing happens after Generate**: a run is already queued or running. The
  panel shows the job's state and any failure.
