// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * "Live captions temporarily unavailable" used to fire at the start of every
 * round and after every hiccup, because the footer keyed off "the lines are
 * empty" — a condition that is routinely true when nothing is wrong. The
 * decision now lives in captionState.ts and reads the server's active/reason
 * flags. This is its truth table.
 */
import { describe, expect, it } from 'vitest'
import {
	captionFooter,
	INACTIVE_POLLS_BEFORE_ALARM,
	updateHistory,
	type CaptionHistory,
	type CaptionPoll,
} from '../../frontend/src/recorder/captionState'

const fresh = (): CaptionHistory => ({ sawLines: false, consecutiveInactive: 0 })

function run(polls: CaptionPoll[]): { state: string; history: CaptionHistory } {
	let history = fresh()
	let state = 'waiting'
	for (const poll of polls) {
		history = updateHistory(poll, history)
		state = captionFooter(poll, history)
	}
	return { state, history }
}

const inactive = (): CaptionPoll => ({ active: false, lines: [] })
const listening = (): CaptionPoll => ({ active: true, lines: [] })
const talking = (): CaptionPoll => ({ active: true, lines: [{ text: 'hi' }] })

describe('the caption footer', () => {
	it('start of round: empty polls are “waiting”, never the alarm', () => {
		// the first polls race the first chunk upload — nothing is wrong
		expect(run([inactive(), inactive()]).state).toBe('waiting')
	})

	it('a live session with nothing committed yet says “listening”', () => {
		expect(run([listening()]).state).toBe('listening')
	})

	it('lines showing means no footer message at all', () => {
		expect(run([talking()]).state).toBe('ok')
	})

	it('at capacity: the honest message, immediately', () => {
		const { state } = run([{ active: false, lines: [], reason: 'capacity' }])
		expect(state).toBe('capacity')
	})

	it('captions that worked and then stopped raise the alarm — after a debounce', () => {
		const polls: CaptionPoll[] = [talking()]
		for (let i = 0; i < INACTIVE_POLLS_BEFORE_ALARM; i++) polls.push(inactive())
		expect(run(polls).state).toBe('unavailable')
	})

	it('a single blip is not an outage', () => {
		expect(run([talking(), inactive()]).state).not.toBe('unavailable')
	})

	it('recovery clears the inactive streak', () => {
		const { history } = run([talking(), inactive(), inactive(), talking()])
		expect(history.consecutiveInactive).toBe(0)
	})

	it('a session that failed before ever producing lines still reaches the alarm', () => {
		// the server says why: reason "error" is the failure cooldown
		const polls: CaptionPoll[] = []
		for (let i = 0; i < INACTIVE_POLLS_BEFORE_ALARM; i++) {
			polls.push({ active: false, lines: [], reason: 'error' })
		}
		expect(run(polls).state).toBe('unavailable')
	})

	it('never-worked with no diagnosis stays calm', () => {
		// captions disabled or a session that never starts: recording is safe,
		// and an alarm about a feature that was never on helps nobody
		const polls = Array.from({ length: 10 }, inactive)
		expect(run(polls).state).toBe('waiting')
	})
})
