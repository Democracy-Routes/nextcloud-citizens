// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Is another phone holding this table's open round?
 *
 * Three things had to be true at once and only one was being checked, so the
 * armed screen told phones their own recording belonged to somebody else:
 *
 *  - the round has to be OPEN. The old check scanned every round, so one
 *    recording of round 1 stuck mid-upload hid the armed display for round 2.
 *  - the recording has to be one this phone did NOT make. The status payload
 *    is scoped to the table, so a phone's own recording looks identical to the
 *    one a replaced device left behind.
 *  - it has to be in a state that means "in progress". FINALIZING and
 *    WAITING_FOR_CHUNKS are never cleared by the silence check, which only
 *    covers RECORDING — so a phone that failed to sync and pressed Back was
 *    told, indefinitely, that another phone had its table.
 *
 * Lives here rather than in either screen because both need it and they had
 * already been copied apart once.
 */
import type { RoundInfo } from './api'

const HOLDING_STATES = ['RECORDING', 'FINALIZING', 'WAITING_FOR_CHUNKS']

export function heldByAnotherDevice(rounds: RoundInfo[]): boolean {
	return rounds.some(
		(round) =>
			round.status === 'ACTIVE' &&
			HOLDING_STATES.includes(round.recorded_state ?? '') &&
			!round.recorded_by_this_device,
	)
}
