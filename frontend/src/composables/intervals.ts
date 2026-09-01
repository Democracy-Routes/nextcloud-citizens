// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/** How often each kind of view refreshes.
 *
 * Six components had picked six different numbers (4, 5, 6, 8, 10 and 20
 * seconds) with no stated reason, and three more never refreshed at all — so
 * during an event the header, the sidebar, the Rounds tab and the Live tab
 * could all disagree about which round was running.
 */

/** The Live tab during an event: the facilitator is acting on this. */
export const LIVE_MS = 4_000

/** Work finishing in the background — transcription, analysis. Visible within
 * a few seconds of happening, without polling as hard as the live view. */
export const BACKGROUND_MS = 15_000

/** Things that change when somebody does something, not on their own. */
export const SLOW_MS = 30_000
