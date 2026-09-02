// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * What a phone does when told to clear its copy.
 *
 * This is the one place in the app where a server-side instruction deletes
 * data from somebody's personal device, and it acts without asking. Two rules
 * make that acceptable, and both are tested here:
 *
 *   * only recordings the SERVER has confirmed are removed, so it can never
 *     destroy the last copy of anything;
 *   * only this assembly's, so a phone used at more than one event does not
 *     lose the other's audio.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { StoredRecording } from '../../frontend/src/recorder/idb'

const store: { recordings: StoredRecording[]; deleted: string[] } = {
	recordings: [],
	deleted: [],
}

vi.mock('../../frontend/src/recorder/api', () => ({
	recorderApi: {},
	RecorderApiError: class extends Error {},
}))
vi.mock('../../frontend/src/recorder/logger', () => ({ clientLog: vi.fn() }))
vi.mock('../../frontend/src/recorder/sha', () => ({ sha256Hex: vi.fn() }))
vi.mock('../../frontend/src/recorder/idb', () => ({
	idb: {
		getRecordings: async () => store.recordings,
		deleteRecording: async (id: string) => {
			store.deleted.push(id)
		},
		deleteChunksFor: async () => undefined,
		async unfinishedRecordings(assemblyId?: string) {
			return store.recordings.filter(
				(r) =>
					!r.serverComplete &&
					(!assemblyId || !r.assemblyId || r.assemblyId === assemblyId),
			)
		},
	},
}))

const { purgeLocalAudio } = await import('../../frontend/src/recorder/purge')

function recording(over: Partial<StoredRecording>): StoredRecording {
	return {
		recordingId: 'rec',
		roundId: 'round',
		tableNumber: 0,
		mimeType: 'audio/webm',
		startedAt: 1,
		finishedAt: null,
		totalChunks: null,
		serverComplete: false,
		...over,
	}
}

beforeEach(() => {
	store.recordings = []
	store.deleted = []
})

describe('purging this phone on the organizer’s request', () => {
	it('removes the audio the server has confirmed', async () => {
		store.recordings = [
			recording({ recordingId: 'safe', assemblyId: 'a1', serverComplete: true }),
		]

		const outcome = await purgeLocalAudio('a1')

		expect(outcome.cleared).toBe(1)
		expect(store.deleted).toEqual(['safe'])
	})

	it('never removes audio the server has not confirmed', async () => {
		// the rule the whole feature rests on — that copy may be the only one
		store.recordings = [
			recording({ recordingId: 'unsent', assemblyId: 'a1', serverComplete: false }),
		]

		const outcome = await purgeLocalAudio('a1')

		expect(outcome.cleared).toBe(0)
		expect(store.deleted).toEqual([])
	})

	it('reports what it held back, so the citizen can be told', async () => {
		store.recordings = [
			recording({ recordingId: 'unsent', assemblyId: 'a1', serverComplete: false }),
			recording({ recordingId: 'safe', assemblyId: 'a1', serverComplete: true }),
		]

		const outcome = await purgeLocalAudio('a1')

		expect(outcome.cleared).toBe(1)
		expect(outcome.keptUnsynced).toBe(1)
	})

	it('leaves another assembly’s audio untouched', async () => {
		store.recordings = [
			recording({ recordingId: 'other', assemblyId: 'a2', serverComplete: true }),
		]

		const outcome = await purgeLocalAudio('a1')

		expect(outcome.cleared).toBe(0)
		expect(store.deleted).toEqual([])
	})

	it('does nothing at all on a phone with no audio', async () => {
		const outcome = await purgeLocalAudio('a1')

		expect(outcome).toEqual({ cleared: 0, keptUnsynced: 0 })
	})
})
