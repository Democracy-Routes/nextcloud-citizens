// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * A phone's local audio belongs to the assembly it was recorded at.
 *
 * Neither of the two places that read it knew that. Both scanned every
 * recording on the device, which is fine when the phones belong to the
 * organisation and are wiped between events — and wrong the moment citizens
 * use their own, which is now a supported way to run an assembly.
 *
 * The consequences were an old recording hijacking a later event's recovery
 * screen before the phone could join it, and clearing one assembly deleting
 * another's audio.
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
					r.recordingId !== '__selftest__' &&
					!r.serverComplete &&
					(!assemblyId || r.assemblyId === assemblyId),
			)
		},
	},
}))

const { clearSynchronizedRecordings } = await import('../../frontend/src/recorder/engine')
const { idb } = await import('../../frontend/src/recorder/idb')

function recording(over: Partial<StoredRecording>): StoredRecording {
	return {
		recordingId: 'rec',
		roundId: 'round',
		tableNumber: 1,
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

describe('finding audio to recover', () => {
	it('ignores another assembly’s unsynced audio', async () => {
		// otherwise a citizen's phone is diverted into recovering March's
		// recording before it can join tonight's assembly
		store.recordings = [
			recording({ recordingId: 'march', assemblyId: 'assembly-march' }),
			recording({ recordingId: 'tonight', assemblyId: 'assembly-tonight' }),
		]

		const found = await idb.unfinishedRecordings('assembly-tonight')

		expect(found.map((r) => r.recordingId)).toEqual(['tonight'])
	})

	it('offers audio predating assemblies only to the unscoped boot scan', async () => {
		// "unknown belongs to whoever asks" made one legacy record block every
		// assembly's purge and let one assembly's clear delete another's. It now
		// matches only the no-arg recovery scan, never a specific assembly.
		store.recordings = [recording({ recordingId: 'legacy', assemblyId: undefined })]

		expect(await idb.unfinishedRecordings('assembly-tonight')).toEqual([])
		expect((await idb.unfinishedRecordings()).map((r) => r.recordingId)).toEqual(['legacy'])
	})

	it('offers everything when there is no assembly to scope by', async () => {
		// the boot path where no session is stored at all
		store.recordings = [recording({ recordingId: 'march', assemblyId: 'assembly-march' })]

		expect(await idb.unfinishedRecordings()).toHaveLength(1)
	})

	it('never offers audio the server already has', async () => {
		store.recordings = [
			recording({ recordingId: 'done', assemblyId: 'a1', serverComplete: true }),
		]

		expect(await idb.unfinishedRecordings('a1')).toEqual([])
	})
})

describe('clearing this assembly’s audio', () => {
	it('leaves another assembly’s copy alone', async () => {
		store.recordings = [
			recording({ recordingId: 'march', assemblyId: 'assembly-march', serverComplete: true }),
			recording({ recordingId: 'tonight', assemblyId: 'assembly-tonight', serverComplete: true }),
		]

		const cleared = await clearSynchronizedRecordings('assembly-tonight')

		expect(cleared).toBe(1)
		expect(store.deleted).toEqual(['tonight'])
	})

	it('never deletes audio the server has not confirmed', async () => {
		// the guarantee the whole feature rests on: this can never destroy the
		// last copy of anything
		store.recordings = [
			recording({ recordingId: 'unsent', assemblyId: 'a1', serverComplete: false }),
		]

		expect(await clearSynchronizedRecordings('a1')).toBe(0)
		expect(store.deleted).toEqual([])
	})

	it('leaves legacy audio alone under a scoped clear, takes it unscoped', async () => {
		// a specific assembly's purge must not delete another event's audio
		// from a citizen's own phone; the done-screen unscoped clear still does
		store.recordings = [
			recording({ recordingId: 'legacy', assemblyId: undefined, serverComplete: true }),
		]

		expect(await clearSynchronizedRecordings('a1')).toBe(0)
		expect(store.deleted).toEqual([])
		expect(await clearSynchronizedRecordings()).toBe(1)
		expect(store.deleted).toEqual(['legacy'])
	})

	it('clears everything confirmed when no assembly is given', async () => {
		store.recordings = [
			recording({ recordingId: 'a', assemblyId: 'x', serverComplete: true }),
			recording({ recordingId: 'b', assemblyId: 'y', serverComplete: true }),
		]

		expect(await clearSynchronizedRecordings()).toBe(2)
	})
})
