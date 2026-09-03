// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Recovered audio must be named after the table it was recorded at.
 *
 * StoredRecording.tableNumber was written as 0 by every caller and read by
 * nobody, so the recovery download used the CURRENT session's table instead.
 * That was indistinguishable from correct until device replacement made phones
 * portable: a citizen's phone can record table 3, be handed to table 7 for the
 * next round, and still hold the first recording's audio — which would then be
 * saved as "citizens-table-7-recovered.webm".
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import RecoverySync from '../../frontend/src/recorder/components/RecoverySync.vue'
import type { StoredRecording } from '../../frontend/src/recorder/idb'
import { mountWithI18n } from './support/mount'

const downloadBlob = vi.fn()
vi.mock('../../frontend/src/download', () => ({
	downloadBlob: (...a: unknown[]) => downloadBlob(...a),
}))

vi.mock('../../frontend/src/recorder/idb', () => ({
	idb: {
		chunksFor: vi.fn().mockResolvedValue([{ seq: 0, blob: new Blob(['a']) }]),
		deleteChunksFor: vi.fn(),
		deleteRecording: vi.fn(),
	},
}))

vi.mock('../../frontend/src/recorder/engine', () => ({
	RecorderEngine: class {
		// the branch that offers the download: the server has lost the
		// recording and the phone still holds the only copy
		state = {
			phase: 'failed',
			errorKind: 'gone',
			localChunks: 1,
			ackedChunks: 0,
			recordingId: 'rec-1',
			startedAt: 1,
		}
		resumeSync = vi.fn().mockResolvedValue(undefined)
	},
	pickMimeType: () => 'audio/webm',
}))

function recording(over: Partial<StoredRecording> = {}): StoredRecording {
	return {
		recordingId: 'rec-1',
		assemblyId: 'a1',
		roundId: 'round-1',
		tableNumber: 3,
		mimeType: 'audio/webm;codecs=opus',
		startedAt: 1,
		finishedAt: null,
		totalChunks: null,
		serverComplete: false,
		...over,
	}
}

/** The phone is sitting at table 7 now. */
const SESSION = {
	session_token: 'tok',
	table_number: 7,
	assembly: { id: 'a1', name: 'Bologna', language: 'en', recording_mode: 'orchestrated' },
	rounds: [],
}

async function save(stored: StoredRecording) {
	const wrapper = mountWithI18n(RecoverySync, {
		props: { session: SESSION, recording: stored },
	})
	await flushPromises()
	const button = wrapper.findAll('button').find((b) => /download audio/i.test(b.text()))
	expect(button, 'the recovery screen should offer to save the audio').toBeTruthy()
	await button!.trigger('click')
	await flushPromises()
	return downloadBlob.mock.calls.at(-1)?.[1] as string
}

beforeEach(() => downloadBlob.mockReset())

describe('the recovered audio filename', () => {
	it('names the table the audio was recorded at, not the one in use now', async () => {
		expect(await save(recording({ tableNumber: 3 }))).toBe('citizens-table-3-recovered.webm')
	})

	it('falls back to the session for audio stored before the field was written', async () => {
		// records written by an older build all carry 0
		expect(await save(recording({ tableNumber: 0 }))).toBe('citizens-table-7-recovered.webm')
	})
})
