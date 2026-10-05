// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * A table that has recorded every session is done: it sees its summaries and
 * the report, not a microphone checklist that reads as "more to do". A session
 * added later brings the checklist back, because the status poll keeps the
 * round list fresh.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import Preflight from '../../frontend/src/recorder/components/Preflight.vue'
import { mountWithI18n } from './support/mount'

const status = vi.fn()

vi.mock('../../frontend/src/recorder/api', async () => {
	const actual = await vi.importActual<Record<string, unknown>>('../../frontend/src/recorder/api')
	return { ...actual, recorderApi: { status: (...a: unknown[]) => status(...a) } }
})
vi.mock('../../frontend/src/recorder/useWakeLock', () => ({ useWakeLock: vi.fn() }))
vi.mock('../../frontend/src/recorder/engine', () => ({ pickMimeType: () => 'audio/webm' }))
vi.mock('../../frontend/src/recorder/idb', () => ({ idb: { selfTest: vi.fn().mockResolvedValue(undefined) } }))

const ROUND = { id: 'round-1', position: 1, title: 'Mobility', question: 'What should change?',
	status: 'ENDED', duration_minutes: 30 }

function session(mode: string, recorded: string | null) {
	return {
		session_token: 'tok', table_number: 1, table_color: 'blue',
		assembly: { id: 'a1', name: 'Bologna', language: 'en', recording_mode: mode },
		rounds: [{ ...ROUND, recorded_state: recorded, table_summary: 'They want later buses.' }],
	}
}

beforeEach(() => {
	status.mockReset()
	Object.defineProperty(navigator, 'mediaDevices', {
		value: { getUserMedia: vi.fn().mockRejectedValue(new Error('no mic in test')) },
		configurable: true,
	})
})

describe('a table that has finished every session', () => {
	it('sees its summaries and the report, not the microphone test', async () => {
		status.mockResolvedValue({
			rounds: [{ ...ROUND, recorded_state: 'READY_FOR_REVIEW', table_summary: 'They want later buses.' }],
			report_available: true,
		})
		const wrapper = mountWithI18n(Preflight, { props: { session: session('independent', 'READY_FOR_REVIEW') } })
		await flushPromises()

		expect(wrapper.text()).toContain('All sessions recorded')
		expect(wrapper.text()).toContain('They want later buses.')
		expect(wrapper.text()).not.toContain('Microphone test')
		expect(wrapper.text()).not.toContain('Record 5-second test')
		expect(wrapper.find('.rc-status-row').exists()).toBe(false)
		expect(wrapper.find('.rc-level').exists()).toBe(false)
		// the one primary action left is the report (the bar's side buttons stay)
		const actions = wrapper.findAll('.rc-bar__main button').map((b) => b.text())
		expect(actions).toEqual(['View assembly report'])
	})

	it('is done in a facilitator-led assembly too, without a READY button', async () => {
		status.mockResolvedValue({ rounds: [{ ...ROUND, recorded_state: 'AUDIO_READY' }], report_available: false })
		const wrapper = mountWithI18n(Preflight, { props: { session: session('orchestrated', 'AUDIO_READY') } })
		await flushPromises()

		expect(wrapper.text()).toContain('All sessions recorded')
		expect(wrapper.text()).not.toContain('Microphone test')
		expect(wrapper.findAll('.rc-bar__main button')).toHaveLength(0)
	})

	it('gets its checklist back when a new session appears', async () => {
		status.mockResolvedValue({
			rounds: [
				{ ...ROUND, recorded_state: 'AUDIO_READY' },
				{ id: 'round-2', position: 2, title: 'Next', question: 'And then?', status: 'NOT_STARTED',
					duration_minutes: 20, recorded_state: null },
			],
			report_available: false,
		})
		const wrapper = mountWithI18n(Preflight, { props: { session: session('independent', 'AUDIO_READY') } })
		await flushPromises()

		expect(wrapper.text()).toContain('Microphone test')
		expect(wrapper.text()).toContain('And then?')
		expect(wrapper.text()).not.toContain('All sessions recorded')
	})

	it('is not done while another phone still holds an open session', async () => {
		status.mockResolvedValue({
			rounds: [{ ...ROUND, status: 'ACTIVE', recorded_state: 'RECORDING', recorded_by_this_device: false }],
			report_available: false,
		})
		const wrapper = mountWithI18n(Preflight, { props: { session: session('independent', 'RECORDING') } })
		await flushPromises()

		expect(wrapper.text()).not.toContain('All sessions recorded')
		expect(wrapper.text()).toContain('already recording on another phone')
	})
})
