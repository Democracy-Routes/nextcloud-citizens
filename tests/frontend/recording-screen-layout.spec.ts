// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The recording screens used to be a single 480px phone column however wide
 * the device actually was. RecordingScreen's scroll zone now carries two
 * wrapper regions — `.rc-main` (what the table is here to read) and `.rc-side`
 * (the phone's own telemetry) — that CSS turns into a two-up grid from 900px
 * and collapses to `display: contents` below it, so the phone DOM order (and
 * therefore its layout) is unchanged. ArmedScreen has no such split: it is
 * one waiting column at every width, so neither region is applicable there.
 *
 * These specs only check structure (which element is whose ancestor) — the
 * actual grid/contents switch is a CSS media query happy-dom does not
 * evaluate, and is covered by hand/visually instead.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ArmedScreen from '../../frontend/src/recorder/components/ArmedScreen.vue'
import RecordingScreen from '../../frontend/src/recorder/components/RecordingScreen.vue'
import { mountWithI18n } from './support/mount'

const status = vi.fn()
const heartbeat = vi.fn().mockResolvedValue(undefined)

vi.mock('../../frontend/src/recorder/api', async () => {
	const actual = await vi.importActual<Record<string, unknown>>('../../frontend/src/recorder/api')
	return {
		...actual,
		recorderApi: {
			status: (...a: unknown[]) => status(...a),
			heartbeat: (...a: unknown[]) => heartbeat(...a),
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
vi.mock('../../frontend/src/recorder/idb', () => ({ idb: { countFor: vi.fn().mockResolvedValue(0) } }))
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
			finish = vi.fn().mockResolvedValue(undefined)
			stop = vi.fn()
			retryNow = vi.fn()
			retrySync = vi.fn()
			recheckServerState = vi.fn()
		},
	}
})

function session(recordingMode: 'orchestrated' | 'plenary') {
	return {
		session_token: 'tok',
		table_number: 1,
		assembly: { id: 'a1', name: 'Bologna', language: 'en', recording_mode: recordingMode },
		rounds: [{ id: 'round-1', position: 1, title: 'Mobility', status: 'ACTIVE', duration_minutes: 30 }],
	}
}

beforeEach(() => {
	status.mockReset().mockResolvedValue({ rounds: [], report_available: false })
	heartbeat.mockClear()
})

describe('RecordingScreen desktop/tablet regions', () => {
	async function mountRecording(recordingMode: 'orchestrated' | 'plenary' = 'orchestrated') {
		const s = session(recordingMode)
		const wrapper = mountWithI18n(RecordingScreen, { props: { session: s, round: s.rounds[0] } })
		await flushPromises()
		return wrapper
	}

	it('wraps the scroll zone in the split regions', async () => {
		const wrapper = await mountRecording()
		const scroll = wrapper.find('.rc-scroll')
		expect(scroll.classes()).toContain('rc-scroll--split')
		expect(wrapper.find('.rc-main').exists()).toBe(true)
		expect(wrapper.find('.rc-side').exists()).toBe(true)
	})

	it('puts the live captions card (and its toggle) in .rc-main', async () => {
		const wrapper = await mountRecording()
		const main = wrapper.find('.rc-main')
		expect(main.text()).toContain('Live transcript')
		expect(main.text()).toContain('Hide live transcript')
		// the telemetry side has none of this
		expect(wrapper.find('.rc-side').text()).not.toContain('Live transcript')
	})

	it('puts the timer ring (and the rest of the telemetry) in .rc-side', async () => {
		const wrapper = await mountRecording()
		const side = wrapper.find('.rc-side')
		expect(side.find('.rc-timer-wrap').exists()).toBe(true)
		expect(side.find('.rc-level').exists()).toBe(true)
		expect(side.find('.rc-techbar').exists()).toBe(true)
		// the timer never ends up on the reading side
		expect(wrapper.find('.rc-main').find('.rc-timer-wrap').exists()).toBe(false)
	})

	it('keeps the add-device button on the telemetry side in plenary mode', async () => {
		const wrapper = await mountRecording('plenary')
		const addDeviceButton = wrapper.findAll('button').find((b) => b.text().includes('Add another phone'))
		expect(addDeviceButton).toBeTruthy()
		expect(addDeviceButton!.element.closest('.rc-side')).toBeTruthy()
		expect(addDeviceButton!.element.closest('.rc-main')).toBeFalsy()
	})
})

describe('ArmedScreen stays a single column — the split is not applicable there', () => {
	it('never introduces .rc-main or .rc-side', async () => {
		const s = session('orchestrated')
		const wrapper = mountWithI18n(ArmedScreen, { props: { session: s } })
		await flushPromises()

		expect(wrapper.find('.rc-main').exists()).toBe(false)
		expect(wrapper.find('.rc-side').exists()).toBe(false)
		// instead it just centres the one column it has
		expect(wrapper.find('.rc-scroll').classes()).toContain('rc-scroll--centered')
	})
})
