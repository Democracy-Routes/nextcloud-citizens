// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The Live tab's own way to finish a table's recording — the organizer's
 * version of the 5-minute silence sweep, for a table that is clearly done
 * but whose phone has not been tapped. And the lines that say when the
 * server (not a person here) already closed it, or is still receiving
 * audio that arrived after such a close.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MonitorTab from '../../frontend/src/components/MonitorTab.vue'
import { mountWithI18n } from './support/mount'

const roundMonitor = vi.fn()
const finishRecording = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: {
		roundMonitor: (...a: unknown[]) => roundMonitor(...a),
		finishRecording: (...a: unknown[]) => finishRecording(...a),
		replaceDevice: vi.fn(),
		startRound: vi.fn(),
		endRound: vi.fn(),
		requestTranscription: vi.fn(),
		recordingTranscript: vi.fn(),
		deviceLogs: vi.fn(),
	},
	ApiError: class extends Error {},
	BASE: '',
}))

const ASSEMBLY = {
	id: 'a1',
	name: 'Bologna',
	rounds: [{ id: 'round-1', position: 1, title: 'R1', status: 'ACTIVE' }],
}

function monitor(recording: Record<string, unknown>) {
	return {
		round_id: 'round-1',
		status: 'ACTIVE',
		started_at: new Date().toISOString(),
		duration_minutes: 30,
		recording_mode: 'orchestrated',
		tables_ready: 0,
		tables_total: 1,
		rounds: [{ id: 'round-1', position: 1, title: 'R1', status: 'ACTIVE' }],
		tables: [
			{
				table_id: 't1',
				number: 3,
				device: { connected: true, seconds_since_contact: 2, status: {} },
				armed: false,
				local_recording_safe: false,
				recording: {
					id: 'rec-1', state: 'RECORDING', started_at: new Date().toISOString(),
					received_chunks: 12, total_chunks: null, error_code: '',
				},
				superseded_recordings: [],
				recorders: [{ slot: 1, label: 'A', connected: true, seconds_since_contact: 2, status: {}, recording: { id: 'rec-1', ...recording } }],
			},
		],
	}
}

const finishButton = (wrapper: ReturnType<typeof mountWithI18n>) => wrapper.find('[data-test="finish-recording"]')

beforeEach(() => {
	roundMonitor.mockReset()
	finishRecording.mockReset().mockResolvedValue({ state: 'FINALIZING', finish_requested_at: new Date().toISOString() })
})

describe('the Finish recording action', () => {
	it('appears for a recorder that is still recording and has not been asked yet', async () => {
		roundMonitor.mockResolvedValue(monitor({ state: 'RECORDING', finish_requested: false }))
		const wrapper = mountWithI18n(MonitorTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		expect(finishButton(wrapper).exists()).toBe(true)
	})

	it('does not appear once the phone has already been asked', async () => {
		roundMonitor.mockResolvedValue(monitor({ state: 'RECORDING', finish_requested: true }))
		const wrapper = mountWithI18n(MonitorTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		expect(finishButton(wrapper).exists()).toBe(false)
		expect(wrapper.find('[data-test="finish-requested"]').exists()).toBe(true)
	})

	it('does not appear for a recording that is no longer RECORDING', async () => {
		roundMonitor.mockResolvedValue(monitor({ state: 'TRANSCRIBED', finish_requested: false }))
		const wrapper = mountWithI18n(MonitorTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		expect(finishButton(wrapper).exists()).toBe(false)
	})

	it('asks first, then calls the API with the recording id', async () => {
		roundMonitor.mockResolvedValue(monitor({ state: 'RECORDING', finish_requested: false }))
		const wrapper = mountWithI18n(MonitorTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		await finishButton(wrapper).trigger('click')
		expect(finishRecording).not.toHaveBeenCalled()

		await wrapper.find('.cz-modal .cz-btn--primary').trigger('click')
		await flushPromises()

		expect(finishRecording).toHaveBeenCalledWith('rec-1')
	})

	it('says the server closed it after silence', async () => {
		roundMonitor.mockResolvedValue(monitor({ state: 'TRANSCRIBED', closed_by: 'silence' }))
		const wrapper = mountWithI18n(MonitorTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		expect(wrapper.find('[data-test="closed-silence"]').text()).toContain('5 minutes of silence')
	})

	it('says it was closed from here, and whether later audio was kept', async () => {
		roundMonitor.mockResolvedValue(monitor({ state: 'TRANSCRIBED', closed_by: 'organizer', continued: true }))
		const wrapper = mountWithI18n(MonitorTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		expect(wrapper.find('[data-test="closed-organizer"]').exists()).toBe(true)
		expect(wrapper.find('[data-test="continued"]').exists()).toBe(true)
	})
})
