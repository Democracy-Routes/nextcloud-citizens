// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The recovery screen may be re-uploading a whole round, unattended. Every
 * other recorder screen held the screen wake lock; this one did not, so an
 * iPhone left on it locked its screen, suspended the page, and the upload
 * stopped until somebody tapped the phone.
 */
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import RecoverySync from '../../frontend/src/recorder/components/RecoverySync.vue'
import type { StoredRecording } from '../../frontend/src/recorder/idb'
import { mountWithI18n } from './support/mount'

vi.mock('../../frontend/src/download', () => ({
	saveBlob: vi.fn(),
	canShareFiles: () => false,
}))

vi.mock('../../frontend/src/recorder/logger', () => ({
	clientLog: vi.fn(),
	ship: vi.fn().mockResolvedValue(undefined),
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
		state = {
			phase: 'syncing',
			errorKind: null,
			localChunks: 1,
			ackedChunks: 0,
			recordingId: 'rec-1',
			startedAt: 1,
			uploadOnline: true,
			serverState: '',
		}
		resumeSync = vi.fn().mockResolvedValue(undefined)
		stop = vi.fn()
	},
	pickMimeType: () => 'audio/webm',
}))

const RECORDING: StoredRecording = {
	recordingId: 'rec-1',
	assemblyId: 'a1',
	roundId: 'round-1',
	tableNumber: 3,
	mimeType: 'audio/webm',
	startedAt: 1,
	finishedAt: null,
	totalChunks: null,
	serverComplete: false,
}

const SESSION = {
	session_token: 'tok',
	expires_at: '',
	table_number: 3,
	assembly: { id: 'a1', name: 'Prova', language: 'it', recording_mode: 'orchestrated' as const },
	rounds: [],
}

const request = vi.fn()
const release = vi.fn().mockResolvedValue(undefined)

beforeEach(() => {
	request.mockReset()
	request.mockResolvedValue({ release, addEventListener: vi.fn(), removeEventListener: vi.fn() })
	Object.defineProperty(navigator, 'wakeLock', { value: { request }, configurable: true })
})

afterEach(() => {
	delete (navigator as { wakeLock?: unknown }).wakeLock
})

describe('RecoverySync', () => {
	it('keeps the screen awake while it uploads', async () => {
		const wrapper = mountWithI18n(RecoverySync, { props: { session: SESSION, recording: RECORDING } })
		await flushPromises()

		expect(request).toHaveBeenCalledWith('screen')

		wrapper.unmount()
		await flushPromises()
		expect(release).toHaveBeenCalled()
	})
})
