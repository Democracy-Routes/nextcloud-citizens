// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The end-of-round finishing behaviour on the phone.
 *
 * Two fixes meet here. "Keep talking" was a write-once latch: once tapped,
 * nothing ever re-armed the auto-finish, so a table that walked away recorded
 * into an ENDED round until the battery died. And the countdown text spliced a
 * whole sentence into a placeholder — "The round has ended. — finishing in 6 s."
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import RecordingScreen from '../../frontend/src/recorder/components/RecordingScreen.vue'
import { mountWithI18n } from './support/mount'

const status = vi.fn()
const finish = vi.fn().mockResolvedValue(undefined)

vi.mock('../../frontend/src/recorder/api', async () => {
	const actual = await vi.importActual<Record<string, unknown>>('../../frontend/src/recorder/api')
	return {
		...actual,
		recorderApi: {
			status: (...a: unknown[]) => status(...a),
			liveTranscript: vi.fn().mockResolvedValue({ lines: [] }),
		},
	}
})
vi.mock('../../frontend/src/recorder/useWakeLock', () => ({ useWakeLock: vi.fn() }))
vi.mock('../../frontend/src/recorder/idb', () => ({ idb: {} }))
vi.mock('../../frontend/src/recorder/engine', () => {
	const state = {
		phase: 'recording', recordingId: 'rec-1', startedAt: Date.now(),
		localChunks: 0, ackedChunks: 0, storageError: false, lowStorage: false,
		uploadOnline: true, uploadFailure: '', serverState: '', error: '',
		errorKind: '', micLost: false,
	}
	return {
		clearSynchronizedRecordings: vi.fn(),
		RecorderEngine: class {
			state = state
			mediaStream = null
			start = vi.fn().mockResolvedValue(undefined)
			finish = (...a: unknown[]) => finish(...a)
			stop = vi.fn()
			retryNow = vi.fn()
			retrySync = vi.fn()
			recheckServerState = vi.fn()
		},
	}
})

const SESSION = {
	session_token: 'tok',
	table_number: 1,
	assembly: { id: 'a1', name: 'Bologna', language: 'en', recording_mode: 'orchestrated' },
	rounds: [{ id: 'round-1', position: 1, title: 'Mobility', status: 'ACTIVE', duration_minutes: 30 }],
}
const ROUND = SESSION.rounds[0]

/** The round has ended server-side. */
const ENDED = { rounds: [{ ...ROUND, status: 'ENDED' }], report_available: false }

beforeEach(() => {
	vi.useFakeTimers()
	status.mockReset().mockResolvedValue(ENDED)
	finish.mockClear()
})

async function mountRecording() {
	const wrapper = mountWithI18n(RecordingScreen, { props: { session: SESSION, round: ROUND } })
	await flushPromises()
	return wrapper
}

describe('the finishing countdown', () => {
	it('shows the ended line and the countdown as separate, self-consistent text', async () => {
		const wrapper = await mountRecording()
		await vi.advanceTimersByTimeAsync(5100) // the 5 s round poll sees ENDED

		const text = wrapper.text()
		expect(text).toContain('The round has ended')
		expect(text).toMatch(/Finishing in \d+ s/)
		// the old splice — a full sentence inside the countdown line — is gone
		expect(text).not.toContain('ended. — finishing')
	})

	it('re-arms the auto-finish after "Keep talking" instead of latching forever', async () => {
		const wrapper = await mountRecording()
		await vi.advanceTimersByTimeAsync(5100)

		await wrapper.findAll('button').find((b) => b.text().includes('Keep talking'))!.trigger('click')
		// during the reprieve, the countdown does not run to zero and finish
		await vi.advanceTimersByTimeAsync(60_000)
		expect(finish).not.toHaveBeenCalled()

		// past the reprieve the next poll re-arms the countdown, which completes
        await vi.advanceTimersByTimeAsync(65_000) // > 120s reprieve
		await vi.advanceTimersByTimeAsync(5100)  // poll re-arms
		await vi.advanceTimersByTimeAsync(16_000) // countdown to zero
		expect(finish).toHaveBeenCalled()
	})
})
