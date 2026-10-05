// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * What the table is told when the microphone goes quiet mid-round.
 *
 * Before, nothing: the timer kept climbing over a recording that had stopped.
 * Now the screen says the capture is interrupted and will resume by itself,
 * says how much of the round was missed once it has, and — if the microphone
 * never came back — explains that in words about the screen going off, not
 * about a phone call nobody received.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import RecordingScreen from '../../frontend/src/recorder/components/RecordingScreen.vue'
import { mountWithI18n } from './support/mount'

const shared = vi.hoisted(() => ({
	state: {
		phase: 'recording',
		recordingId: 'rec-1',
		startedAt: Date.now(),
		localChunks: 3,
		ackedChunks: 3,
		storageError: false,
		lowStorage: false,
		uploadOnline: true,
		uploadFailure: '',
		serverState: '',
		error: '',
		errorKind: '',
		micLost: false,
		micLostCause: '',
		captureInterrupted: false,
		interruptedSince: 0,
		interruptions: [] as Array<{ from: number; to: number; cause: string }>,
		segment: 0,
	},
	wake: { held: true, supported: true },
}))

vi.mock('../../frontend/src/recorder/api', async () => {
	const actual = await vi.importActual<Record<string, unknown>>('../../frontend/src/recorder/api')
	return {
		...actual,
		recorderApi: {
			status: vi.fn().mockResolvedValue({ rounds: [], report_available: false }),
			liveTranscript: vi.fn().mockResolvedValue({ lines: [] }),
			heartbeat: vi.fn().mockResolvedValue({ ok: true }),
		},
	}
})
vi.mock('../../frontend/src/recorder/useWakeLock', async () => {
	const { ref } = await import('vue')
	return {
		useWakeLock: () => ({ held: ref(shared.wake.held), supported: shared.wake.supported }),
		wakeLockHeld: ref(shared.wake.held),
	}
})
vi.mock('../../frontend/src/recorder/idb', () => ({ idb: { countFor: vi.fn().mockResolvedValue(0) } }))
vi.mock('../../frontend/src/recorder/engine', () => ({
	clearSynchronizedRecordings: vi.fn(),
	RecorderEngine: class {
		state = shared.state
		mediaStream = null
		start = vi.fn().mockResolvedValue(undefined)
		finish = vi.fn().mockResolvedValue(undefined)
		stop = vi.fn()
		retryNow = vi.fn()
		retrySync = vi.fn()
		recheckServerState = vi.fn()
	},
}))

const SESSION = {
	session_token: 'tok',
	table_number: 1,
	assembly: { id: 'a1', name: 'Bologna', language: 'en', recording_mode: 'orchestrated' },
	rounds: [{ id: 'round-1', position: 1, title: 'Mobility', status: 'ACTIVE', duration_minutes: 30 }],
}
const ROUND = SESSION.rounds[0]

beforeEach(() => {
	vi.useFakeTimers()
	Object.assign(shared.state, {
		phase: 'recording', micLost: false, micLostCause: '', captureInterrupted: false,
		interruptions: [], segment: 0,
	})
	shared.wake.held = true
	shared.wake.supported = true
})

async function mounted() {
	const wrapper = mountWithI18n(RecordingScreen, { props: { session: SESSION, round: ROUND } })
	await flushPromises()
	return wrapper
}

describe('the recording screen during an interruption', () => {
	it('says the capture is interrupted and will resume by itself', async () => {
		shared.state.captureInterrupted = true
		const wrapper = await mounted()

		expect(wrapper.text()).toContain('The microphone stopped')
		expect(wrapper.text()).toContain('resumes by itself')
		expect(wrapper.text()).toContain('interrupted')
	})

	it('says how much of the round was missed once capture is back', async () => {
		shared.state.interruptions = [{ from: 1_000, to: 13_000, cause: 'capture_stalled' }]
		const wrapper = await mounted()

		expect(wrapper.text()).toContain('12 s of the session were not captured')
		expect(wrapper.text()).not.toContain('The microphone stopped')
	})

	it('shows nothing of the sort on an uninterrupted round', async () => {
		const wrapper = await mounted()
		expect(wrapper.text()).not.toContain('not captured')
		expect(wrapper.text()).not.toContain('The microphone stopped')
		expect(wrapper.text()).not.toContain('auto-lock')
	})

	it('names the screen going off, not a call, when that is what took the microphone', async () => {
		Object.assign(shared.state, { phase: 'syncing', micLost: true, micLostCause: 'capture_stalled' })
		const wrapper = await mounted()

		expect(wrapper.text()).toContain('after the screen went off')
		expect(wrapper.text()).not.toContain('a call or another app')
	})

	it('still blames a call when a call it was', async () => {
		Object.assign(shared.state, { phase: 'syncing', micLost: true, micLostCause: 'track_ended' })
		const wrapper = await mounted()

		expect(wrapper.text()).toContain('a call or another app')
	})

	it('repeats it on the finished screen, where the table actually looks', async () => {
		Object.assign(shared.state, { phase: 'done', micLost: true, micLostCause: 'track_muted' })
		const wrapper = await mounted()

		expect(wrapper.text()).toContain('after the screen went off')
	})

	it('tells the table to set auto-lock to Never when the phone cannot hold the screen', async () => {
		shared.wake.supported = false
		shared.wake.held = false
		const wrapper = await mounted()

		expect(wrapper.text()).toContain('set auto-lock to Never')
	})
})
