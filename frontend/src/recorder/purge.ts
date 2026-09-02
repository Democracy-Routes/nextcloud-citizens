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

/** Is this phone still working on something the server has not got?
 *
 * A structural gate rather than a flag the parent maintains: whether audio is
 * still in flight is a fact about storage, and reading it directly cannot get
 * out of step with the component tree the way an event-driven flag can. While
 * this is true the purge is deferred, not refused — the next poll asks again.
 */
export async function hasUnfinishedAudio(assemblyId: string): Promise<boolean> {
	try {
		return (await idb.unfinishedRecordings(assemblyId)).length > 0
	} catch {
		return true // cannot tell: assume there is, and leave the audio alone
	}
}
