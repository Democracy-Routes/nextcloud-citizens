// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Telling a phone its own recording belongs to somebody else.
 *
 * "This table is already recording on another phone" is shown at the worst
 * possible moment — a table whose device has just died — so it has to be true.
 * It was derived from recorded_state alone, and that field is scoped to the
 * TABLE, not the session: a phone's own recording and the one left behind by
 * the device it replaced look identical in the status payload.
 *
 * Two ordinary paths reached it. A failed sync offers "Back", which returns to
 * the armed screen while the phone's own recording sits in WAITING_FOR_CHUNKS
 * — a state the silence check never clears, because that only covers
 * RECORDING. And skipping recovery lands on Preflight with the same shape.
 */
import { describe, expect, it } from 'vitest'
import type { RoundInfo } from '../../frontend/src/recorder/api'
import { heldByAnotherDevice } from '../../frontend/src/recorder/holding'

function round(over: Partial<RoundInfo> = {}): RoundInfo {
	return {
		id: 'round-1',
		position: 1,
		title: 'Mobility',
		question: 'What should change?',
		duration_minutes: 30,
		status: 'ACTIVE',
		recorded_state: null,
		...over,
	}
}

describe('heldByAnotherDevice', () => {
	it('is true when another phone is recording the open round', () => {
		expect(
			heldByAnotherDevice([
				round({ recorded_state: 'RECORDING', recorded_by_this_device: false }),
			]),
		).toBe(true)
	})

	// the whole point: this is the phone that MADE the recording
	it.each(['RECORDING', 'FINALIZING', 'WAITING_FOR_CHUNKS'])(
		'is false for this phone’s own recording in %s',
		(state) => {
			expect(
				heldByAnotherDevice([
					round({ recorded_state: state, recorded_by_this_device: true }),
				]),
			).toBe(false)
		},
	)

	it('ignores rounds that are not open', () => {
		// a round-1 recording stuck mid-upload used to suppress the armed
		// display for round 2, because the check scanned every round
		expect(
			heldByAnotherDevice([
				round({ id: 'r1', status: 'ENDED', recorded_state: 'WAITING_FOR_CHUNKS' }),
				round({ id: 'r2', position: 2, status: 'ACTIVE', recorded_state: null }),
			]),
		).toBe(false)
	})

	it('is false when nothing has recorded the round', () => {
		expect(heldByAnotherDevice([round()])).toBe(false)
	})

	it('is false for a round already finished by another phone', () => {
		// AUDIO_READY is not "in progress" — that table is done, not held
		expect(
			heldByAnotherDevice([
				round({ recorded_state: 'AUDIO_READY', recorded_by_this_device: false }),
			]),
		).toBe(false)
	})

	it('treats a missing flag as another device, which is the safe default', () => {
		// an older server that does not send the field: better to suggest
		// asking the facilitator than to claim the table is free
		expect(heldByAnotherDevice([round({ recorded_state: 'RECORDING' })])).toBe(true)
	})
})
