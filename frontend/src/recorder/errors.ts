// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/** What a failed request means for a phone in the middle of an assembly.
 *
 * The distinction matters more here than anywhere else in the app: treating a
 * dropped WiFi packet as "this session is over" throws away a table's place in
 * the assembly and, with it, the route to any audio still waiting on the
 * device. Getting it backwards in the other direction only costs a retry.
 */
import { RecorderApiError } from './api'

/** The server definitively no longer accepts this session or recording —
 * revoked invite, deleted assembly, reset instance. Retrying cannot succeed. */
export function isGoneError(error: unknown): boolean {
	return error instanceof RecorderApiError && [401, 403, 404, 410].includes(error.status)
}

/** Network failures and server-side hiccups (busy database, a restart, rate
 * limiting) are worth retrying; only definitive rejections are not. */
export function isTransientError(error: unknown): boolean {
	if (!(error instanceof RecorderApiError)) return true // fetch/network failure
	return error.status === 429 || error.status >= 500
}

/** What to do with a stored session whose status check just failed.
 *
 * 'clear' discards the session and sends the table back to the facilitator for
 * a new QR code. That must happen ONLY when the server has actually rejected
 * it. Any failure used to clear it, so one bad response on venue WiFi during a
 * reload disconnected the table permanently — and because the recovery scan
 * only ran on the way into a live session, it also put whatever audio was
 * still on the phone out of reach of the UI.
 */
export function decideOnStatusFailure(error: unknown): 'clear' | 'retry' {
	return isGoneError(error) ? 'clear' : 'retry'
}
