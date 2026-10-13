/*
 * One clock per table (R5): a planned duration counts from the FIRST
 * recorder's start at the table, which the status poll reports as
 * table_started_at, so a phone added later shows the same elapsed time and
 * finishes together with the others instead of running its own timer.
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

const ROUND = { id: 'round-1', position: 1, title: 'Mobility', status: 'ACTIVE', duration_minutes: 1 }
const SESSION = {
	session_token: 'tok',
	table_number: 1,
	assembly: { id: 'a1', name: 'Bologna', language: 'en', recording_mode: 'independent' },
	rounds: [ROUND],
}

beforeEach(() => {
	vi.useFakeTimers()
	status.mockReset().mockResolvedValue({ rounds: [ROUND], report_available: false })
	finish.mockClear()
})

async function mountRecording(round: Record<string, unknown>) {
	const wrapper = mountWithI18n(RecordingScreen, { props: { session: SESSION, round } })
	await flushPromises()
	return wrapper
}

describe('one clock per table', () => {
	it('counts the planned time from the first recorder at the table', async () => {
		const twoMinutesAgo = new Date(Date.now() - 120_000).toISOString()
		const wrapper = await mountRecording({ ...ROUND, table_started_at: twoMinutesAgo })
		await vi.advanceTimersByTimeAsync(1_000) // one clock tick
		// the elapsed clock is the table's, not this phone's
		expect(wrapper.text()).toMatch(/02:0\d/)
		// a one-minute session that started two minutes ago is over: the
		// finish countdown begins on this phone too
		expect(wrapper.text()).toMatch(/Finishing in \d+ s/)
	})

	it('keeps its own clock when nobody at the table started before it', async () => {
		const wrapper = await mountRecording({ ...ROUND, table_started_at: null })
		await vi.advanceTimersByTimeAsync(1_000)
		expect(wrapper.text()).toMatch(/00:0\d/)
		expect(wrapper.text()).not.toMatch(/Finishing in/)
	})

	it('follows the table start the poll reports later', async () => {
		const wrapper = await mountRecording({ ...ROUND, table_started_at: null })
		status.mockResolvedValue({
			rounds: [{ ...ROUND, table_started_at: new Date(Date.now() - 90_000).toISOString() }],
			report_available: false,
		})
		await vi.advanceTimersByTimeAsync(8_600) // the 8 s round poll, then a tick
		expect(wrapper.text()).toMatch(/Finishing in \d+ s/)
	})
})
