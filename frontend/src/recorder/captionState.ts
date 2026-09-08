// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * What the caption footer should say, decided honestly.
 *
 * The old rule was "empty lines = show the alarm", which fired at the start of
 * every round (the first polls legitimately return no lines yet) and for a
 * whole minute after any hiccup — a scary message for situations that were
 * mostly fine. The server now says WHY there are no captions (its `active`
 * flag and a `reason`), and this maps that to one of five footer states.
 *
 * Kept as a pure function so the flicker cases are unit-testable without
 * mounting the recording screen.
 */

export interface CaptionPoll {
	active: boolean
	lines: unknown[]
	reason?: string
}

export interface CaptionHistory {
	/** captions have appeared at least once this recording */
	sawLines: boolean
	/** successful polls in a row reporting an inactive session */
	consecutiveInactive: number
}

export type CaptionFooter = 'ok' | 'waiting' | 'listening' | 'capacity' | 'unavailable'

/** Polls in a row that must report "inactive" before the alarm shows.
 * At one poll per 6 s this is ~18 s — enough to ride out the start-of-round
 * race and a single blip, short enough that a real outage is still told. */
export const INACTIVE_POLLS_BEFORE_ALARM = 3

/** Fold one poll result into the history (call before deciding the state). */
export function updateHistory(result: CaptionPoll, history: CaptionHistory): CaptionHistory {
	return {
		sawLines: history.sawLines || result.lines.length > 0,
		consecutiveInactive: result.active ? 0 : history.consecutiveInactive + 1,
	}
}

export function captionFooter(result: CaptionPoll, history: CaptionHistory): CaptionFooter {
	if (result.lines.length > 0) return 'ok'
	// intentionally off: the room is at the provider's concurrency cap
	if (result.reason === 'capacity') return 'capacity'
	// a live session that simply has nothing committed yet — calm, not an alarm
	if (result.active) return 'listening'
	// the alarm needs both persistence (not a one-poll blip) and evidence that
	// something actually broke: captions that were working stopped, or the
	// server says the session failed ("error", the post-failure cooldown)
	const persistent = history.consecutiveInactive >= INACTIVE_POLLS_BEFORE_ALARM
	if (persistent && (history.sawLines || result.reason === 'error')) {
		return 'unavailable'
	}
	// still connecting, or a blip not yet worth alarming anyone about
	return history.sawLines ? 'listening' : 'waiting'
}
