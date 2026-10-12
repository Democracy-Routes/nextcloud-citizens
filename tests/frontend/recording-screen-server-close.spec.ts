// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The phone finds out, from its own status poll, that the server already
 * finished its recording — closed by the 5-minute silence sweep, or by the
 * organizer from the Live tab — or that the organizer has asked it to
 * finish. The engine itself is never told anything changed; this screen is
 * the only thing that has to notice and (for the organizer cases) call the
 * existing finishRecording() so the phone's own state catches up.
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
vi.mock('../../frontend/src/recorder/useWakeLock', async () => {
	const { ref } = await import('vue')
	return {
		useWakeLock: () => ({ held: ref(true), supported: true }),
		wakeLockHeld: ref(true),
	}
})
vi.mock('../../frontend/src/recorder/idb', () => ({ idb: {} }))
vi.mock('../../frontend/src/recorder/engine', () => {
	const state = {
		phase: 'recording', recordingId: 'rec-1', startedAt: Date.now(),
		localChunks: 0, ackedChunks: 0, storageError: false, lowStorage: false,
		uploadOnline: true, uploadFailure: '', serverState: '', error: '',
		errorKind: '', micLost: false, micLostCause: '', captureInterrupted: false,
		interruptedSince: 0, interruptions: [], segment: 0,
	}
	return {
		clearSynchronizedRecordings: vi.fn(),
		readBatteryLevel: vi.fn().mockResolvedValue(undefined),
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

/** The round is still open server-side — only the phone's own recording was
 * closed or is being asked to finish. */
const ACTIVE = { rounds: [{ ...ROUND, status: 'ACTIVE' }], report_available: false }

function withNotice(notice: Record<string, unknown> | null) {
	return { ...ACTIVE, recording_notice: notice }
}

beforeEach(() => {
	vi.useFakeTimers()
	status.mockReset().mockResolvedValue(ACTIVE)
	finish.mockClear()
})

async function mountRecording() {
	const wrapper = mountWithI18n(RecordingScreen, { props: { session: SESSION, round: ROUND } })
	await flushPromises()
	return wrapper
}

describe('a recording the server already closed', () => {
	it('shows the silence card and never touches the engine', async () => {
		status.mockResolvedValue(
			withNotice({
				recording_id: 'rec-1', round_id: 'round-1', closed_by: 'silence',
				closed_at: '2026-10-13T10:15:00Z', finish_requested: false, audio_added: false,
			}),
		)
		const wrapper = await mountRecording()
		await vi.advanceTimersByTimeAsync(8100)

		const card = wrapper.find('[data-test="server-closed"]')
		expect(card.exists()).toBe(true)
		expect(card.text()).toMatch(/\d{1,2}:\d{2}/)
		expect(finish).not.toHaveBeenCalled()
	})

	it('finishes exactly once when the organizer asks, across two polls', async () => {
		status.mockResolvedValue(
			withNotice({
				recording_id: 'rec-1', round_id: 'round-1', closed_by: null,
				closed_at: null, finish_requested: true, audio_added: false,
			}),
		)
		const wrapper = await mountRecording()
		await vi.advanceTimersByTimeAsync(8100)
		expect(wrapper.find('[data-test="finish-requested"]').exists()).toBe(true)

		await vi.advanceTimersByTimeAsync(8000)
		expect(finish).toHaveBeenCalledTimes(1)
	})

	it('hides the card once OK is tapped, and keeps it hidden for the same close', async () => {
		status.mockResolvedValue(
			withNotice({
				recording_id: 'rec-1', round_id: 'round-1', closed_by: 'silence',
				closed_at: '2026-10-13T10:15:00Z', finish_requested: false, audio_added: false,
			}),
		)
		const wrapper = await mountRecording()
		await vi.advanceTimersByTimeAsync(8100)
		expect(wrapper.find('[data-test="server-closed"]').exists()).toBe(true)

		await wrapper.find('[data-test="server-closed-ok"]').trigger('click')
		expect(wrapper.find('[data-test="server-closed"]').exists()).toBe(false)

		// the same closed_at on the next poll stays hidden
		await vi.advanceTimersByTimeAsync(8000)
		expect(wrapper.find('[data-test="server-closed"]').exists()).toBe(false)
	})
})
