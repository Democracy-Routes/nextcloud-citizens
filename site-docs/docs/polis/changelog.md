# Changelog

This page is a **static copy** of the Citizen-polis-orbis changelog (the fork's part only; the PolisOrbis changelog the repository
started from is not reproduced). It is refreshed by hand when `CHANGELOG.md` in the
[repository](https://github.com/Democracy-Routes/polisorbis) changes. Newest first. Copied on 2026-11-14.

## 2026-11-14
- Voting page on phones: Disagree is now the left button and Agree the right one, matching the swipe directions. The load-time hint runs on every page load (not once per browser) and shows both ways to vote: the card nudges right and left with the stamp, the tint and the matching button lighting up, under a caption.
- Fixed: on touch screens the browser took a horizontal drag of the card for a scroll after the first move and cancelled the pointer events, so the card did not follow the finger (mouse drags in the browser checks never showed it). Horizontal touch moves now prevent the browser's default; vertical ones still scroll the statement.
- Fixed: the participation stylesheet `css/polis.css` has a fixed name and a one-year cache lifetime, so phones kept the old stylesheet with the new script after a deploy (yesterday's swipe redesign showed no movement on such phones). The page now links it with a per-build query string.

## 2026-11-13
- `GET /api/v3/citizens/ping`, same `Authorization: Bearer <api key>` as the import: answers the key's owner e-mail and the instance URL. It is what Citizens' Settings "Test connection" calls (Citizens 0.9, tranche 3c).
- Swipe voting on phones redesigned: a card deck (two decorative slivers, the next statement is not prefetched), Agree/Disagree stamps and a tint that grow with the drag, the card pivots the way the finger pulls it, a fling exits faster, the old card no longer snaps back to the centre before the next one appears, the buttons use the same exit animation, and no second vote can be sent while a card is leaving.

## 2026-11-04
- **Data loss found and stopped.** PolisOrbis 1.4+ ships a sandbox purge: a cron job in the server container that every night at 03:00 deletes every conversation not modified for 48 hours and the users left without one. It was active on polis.democracyroutes.com from the first day; the conversations of 29 to 31 October were deleted on 2 November. The job and its unauthenticated route `POST /api/v3/prune` now exist only when `PRUNE_ENABLED=true`; both stacks set it to false, the generated `.env` too, and the nginx site blocks the route as well. No backups existed, the data is not recoverable.
- Sign-in fix: the forms and the account scripts trim and lowercase the email before hashing it. Phone keyboards capitalise the first letter of the email field, which produced a different hash and "unknown user". The email fields are now `type=email` with autocapitalisation off.
- One repository: deployment (`deploy/`), documentation (`docs/`), the agent
  brief and this changelog moved into the code repository. `deploy/polis.sh`
  and `deploy/build-images.sh` run from the repository root. Default branch
  `main`. README rewritten.
- `example.env` lists the AI drafting variables.

## 2026-10-30
- AI drafting takes the organizer's request as the subject; the conversation's title and description are background only (statements no longer drift towards the title).
- "Show on the home page" switch per conversation (new column `is_listed`, apply with `deploy/prod/migrate.sh`), public `GET /api/v3/listed-conversations`, and a home page that lists those open conversations with a Vote button and the report link. Listing conversations by `context` now needs a login.
- Site title is "Polis" (`P_TITLE`).
- Report on phones: compact header with a settings menu, section nav with icons, a summary section first (strongest consensus, most divisive, groups, uncertainty), one section per screen with swipe between them, statement rows showing the overall bar with the groups behind a tap, a zoomable opinion map (pinch, drag, double-tap). Laptops unchanged.
- Swipe to vote on phones (right agrees, left disagrees) with a one-time nudge and caption; buttons unchanged.
- Organizer pages reorganised: one top bar (Conversations, Account, Sign out), three sections per conversation (Set up, Moderate, Results) instead of seven links, conversation list as cards with status and counts, set-up form in titled sections with the delete at the bottom, moderation queues as pills with counts, results page with copy link, live numbers and the report link; old `/share`, `/stats`, `/reports` paths still work.
- The "Back to the start" button after the last statement goes to `P_HOME_URL` (default `/home`) instead of the logo link.
- App-style voting page on phones (not embedded): four panes (vote, write, groups, info) with a bottom tab bar and no page scrolling; the statement card fills the screen with the vote buttons at the bottom; tablets, laptops and embeds unchanged.
- Report (analysis page) redesigned for phones and laptops: one stylesheet with the brand tokens, sticky header with section nav, stat tiles, a beeswarm that follows its container, the opinion map on a viewBox with labels that scale, statement rows as stacked bars (cards on phones, a grid from 768px), English and Italian copy (`?lang=it`), real error messages, print layout; numbers unchanged; dead code (matrix, box plot, Radium) removed.
- `POST /api/v3/citizens/import` creates a conversation, its report and the seed statements from a Citizens export in one call; API keys as `Authorization: Bearer`; personal-data guard; `deploy/prod/create-apikey.sh` and `delete-apikey.sh`; the bulk CSV route caps statements at 400 characters.
- Organizer pages centred in a 72em container on laptops; sign-in card centred.

## 2026-10-29
- Fork of PolisOrbis 1.5.0 at github.com/Democracy-Routes/polisorbis: CSV upload of seed statements (Citizens `position,statement` or `comment_text`), no third-party requests from report and participation pages, Democracy Routes branding.
- `deploy/build-images.sh` builds the server and file-server images with memory caps; `deploy/polis.sh local|prod` runs either stack.
- polis.democracyroutes.com live: host nginx site (`deploy/prod/nginx/`), Let's Encrypt certificate, public sign-up blocked, `deploy/prod/create-account.sh` for team accounts.
- Team-account scripts store and look up `md5(email)@dummy.net` like PolisOrbis's forms; `deploy/prod/reset-password.sh` added.
- Built-in privacy and terms pages (EN/IT) with operator details from `P_OPERATOR_*` build variables; footer links default to them.
- AI statement drafting (`/api/v3/ai/status`, `/api/v3/ai/draft-statements`, admin panel with review list, refine and add); provider-agnostic, off by default. The privacy page reads the provider (name, region, privacy policy) from the public `/api/v3/ai/status`.
- Visual refresh (democracyroutes.com palette, self-hosted fonts, pill vote buttons, focus rings, phone layouts); tokens documented in `docs/branding.md`.
- Polish pass (voting page header/card/help texts/write box, phone nav rows, labelled sign-in, quieter delete, favicon and title on the voting page, Orbis survey off by default).

## 2026-10-28
- Project created: README, agent brief, integration contract, decisions, host notes.
- Decision: self-hosted Polis in Europe; PolisOrbis 1.5.0 chosen over upstream Polis 2 and Agora. Local install with published images, memory limits, localhost only, all outbound services off.
- Verified the owner API for conversations and seed comments; documented in `docs/citizens-integration.md`.
