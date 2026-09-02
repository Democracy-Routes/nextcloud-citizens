// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Acting on the organizer's request to clear this phone's local audio.
 *
 * Every recording is written to the phone's own storage before it is uploaded,
 * so at the end of an assembly each phone still holds its table's audio. When
 * the phones belong to citizens rather than the organisation, that means people
 * walk home with a recording of the discussion without knowing it.
 *
 * The organizer asks once; the request arrives on the status poll each recorder
 * already makes. Two rules make this safe to act on without asking again:
 *
 *   * only recordings the SERVER has confirmed it holds are removed, so this
 *     can never destroy the last copy of anything;
 *   * only this assembly's, so a phone used at more than one event does not
 *     lose the other's audio.
 *
 * And the phone says what it did. It is somebody's own device — doing this
 * silently would be the wrong way round.
 */
import { clearSynchronizedRecordings } from './engine'
import { idb } from './idb'

export interface PurgeOutcome {
	cleared: number
	/** Held back because the server has not confirmed it — never deleted. */
	keptUnsynced: number
}

export async function purgeLocalAudio(assemblyId: string): Promise<PurgeOutcome> {
	const before = await idb.unfinishedRecordings(assemblyId)
	const cleared = await clearSynchronizedRecordings(assemblyId)
	return { cleared, keptUnsynced: before.length }
}
