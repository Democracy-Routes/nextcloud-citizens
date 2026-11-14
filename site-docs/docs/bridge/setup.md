# Connecting an installation

A Citizens installation (Nextcloud ExApp or standalone) is connected to one Polis instance by a URL and an API key. The Polis
instance must be the **Citizens-Polis fork**, because only it has the import and ping endpoints; a stock PolisOrbis or Polis answers
404.

## Steps

1. **The Polis operator issues a key** for a team account on the Polis host:

    ```sh
    ./deploy/prod/create-apikey.sh <email>
    ```

    The e-mail is that of an existing team account (create one with `create-account.sh` first if needed). The key (`pkey_` plus 17
    characters) is **printed once**. Hand it to the Citizens administrator through a secure channel, never through git or chat.
    The conversations the key creates belong to its account and show up in that account's list like any other.

2. **The Citizens administrator enters both values** in Settings, AI, Polis: the instance URL (`http` or `https`, for example
   `https://polis.democracyroutes.com`) and the key. The key is stored like the other API keys, is never returned by any API and is
   never shown again; the interface shows only that it is configured. See the [Settings reference](../admin/settings.md#polis).

3. **Press Test connection.** Citizens calls `GET <instance>/api/v3/citizens/ping` with the key and shows "Connected" and whose key
   it is (the account's stored e-mail, which for script-made accounts is the hashed `...@dummy.net` form). It does not create
   anything.

4. With both set, organizers get **Send to Polis** in Results, Polis seeds. Without them the button is disabled and the export
   files remain the manual route.

## One key per installation

Issue **one key per Citizens installation**, ideally on its own team account if you want to tell them apart. The import rate limit
(20 per hour) is counted per account, so installations sharing an account share that budget.

## Rotating or deleting a key

```sh
./deploy/prod/delete-apikey.sh <email>     # revokes every key of that account
./deploy/prod/create-apikey.sh <email>     # then issue a new one
```

`delete-apikey.sh` removes **all** keys of the account, so every installation using that account stops working until it is given a
new key. After the new key is pasted into Settings, press Test connection. Use `POLIS_ENV=local` for the local stack.

## Network and egress

Citizens makes the calls; Polis makes none to Citizens.

| From | To | Why | When |
|---|---|---|---|
| Citizens server | `<instance>/api/v3/citizens/ping` | Test connection | When an administrator presses the button |
| Citizens server | `<instance>/api/v3/citizens/import` | Send the statements | When an organizer presses Send to Polis |

The Citizens host therefore needs outbound HTTPS to the Polis host and nothing inbound. The send runs as a background job
(`PUSH_POLIS`) with a 120 second timeout, never inside a request. The Polis host's nginx does not block the Citizens routes.
Citizens-side egress is also listed in [Providers and egress](../admin/providers-egress.md).

## Troubleshooting

| Message in Citizens | Cause | What to do |
|---|---|---|
| "Could not reach the Polis instance: ..." | Wrong URL, DNS, firewall or timeout | Check the URL and outbound HTTPS from the Citizens host |
| "Polis rejected the API key (HTTP 401)" | No key sent | Enter the key in Settings |
| "Polis rejected the API key (HTTP 403)" | The key does not exist: mistyped, or revoked by `delete-apikey.sh` | Ask the operator for a new key |
| "This Polis instance has no Citizens endpoint (HTTP 404)" | The URL points at a Polis that is not the fork | Use the Citizens-Polis fork's URL |
| "Polis is rate limiting imports (HTTP 429)" | More than 20 imports in an hour for the account | The job retries later; wait, or use another account's key |
| "Polis refused N statement(s) that look like personal data (positions ...)" (HTTP 400) | A statement has an e-mail address, a phone number (8 or more digits), a table reference or is wrapped in quotation marks | Edit the marked statements (**Refused by Polis** badge) and send again. Nothing was created |
| "Polis rejected the statements (...)" (HTTP 400) | Out of limits: no statement, more than 200, or one over 400 characters | Fix the statements; the message lists `field: reason` |
| "Polis is not configured" | URL or key missing | Enter both in Settings |
| "No approved statements to send" | Every statement is a draft or rejected | Approve at least one |
| "Send the statements to Polis first" (409) | Publishing the poll before a successful send | Send first |

Permanent errors (key, refused content, missing endpoint) are not retried; a 429 or a network failure can be.
