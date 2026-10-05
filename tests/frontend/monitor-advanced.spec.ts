// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The Live tab's advanced diagnostics: off by default (the normal view words
 * problems), one line of heartbeat facts per recorder when switched on.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MonitorTab from '../../frontend/src/components/MonitorTab.vue'
import { mountWithI18n } from './support/mount'

const roundMonitor = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: {
		roundMonitor: (...args: unknown[]) => roundMonitor(...args),
		roundMessages: vi.fn().mockResolvedValue([]),
		startRound: vi.fn(),
		endRound: vi.fn(),
		requestTranscription: vi.fn(),
		recordingTranscript: vi.fn(),
		deviceLogs: vi.fn(),
		replaceDevice: vi.fn(),
	},
	ApiError: class extends Error {},
	BASE: '',
}))

const ASSEMBLY = {
	id: 'a1', name: 'Bologna', recording_mode: 'orchestrated',
	rounds: [{ id: 'round-1', position: 1, title: 'R1', status: 'ACTIVE' }],
}

beforeEach(() => {
	localStorage.removeItem('citizens-live-advanced')
	roundMonitor.mockReset()
	roundMonitor.mockResolvedValue({
		round_id: 'round-1', status: 'ACTIVE', started_at: new Date().toISOString(), duration_minutes: 30,
		recording_mode: 'orchestrated', tables_ready: 1, tables_total: 1,
		tables: [{
			table_id: 't3', number: 3, color_key: 'orange',
			device: { connected: true, seconds_since_contact: 4, status: { recording_active: true, storage_ok: true, capture_ok: true } },
			armed: false, local_recording_safe: true,
			recording: { id: 'rec3', state: 'RECORDING', started_at: new Date().toISOString(), received_chunks: 10, total_chunks: null, error_code: '' },
			superseded_recordings: [],
			recorders: [
				{ slot: 1, label: 'A', connected: true, seconds_since_contact: 4,
					status: { battery_level: 0.42, storage_free_mb: 812.4, local_chunks: 12, acked_chunks: 10, screen_awake: true, visible: true, capture_ok: true },
					recording: { id: 'rec3', state: 'RECORDING', live_source: true } },
				{ slot: 2, label: 'B', connected: false, seconds_since_contact: null, status: {}, recording: null },
			],
			readiness: { status: 'NEEDS_ATTENTION', reasons: [{ code: 'RECORDER_OFFLINE', severity: 'warning', slot: 2, data: {} }] },
		}],
		readiness: { status: 'NEEDS_ATTENTION', ready: 0, needs_attention: 1, blocked: 0 }, rounds: ASSEMBLY.rounds,
	})
})

describe('advanced diagnostics', () => {
	it('is off by default and shows the heartbeat facts per recorder when on', async () => {
		const wrapper = mountWithI18n(MonitorTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()
		expect(wrapper.find('[data-test="diagnostics"]').exists()).toBe(false)
		await wrapper.find('[data-test="advanced"]').trigger('click')
		const lines = wrapper.findAll('[data-test="diagnostics"] li').map((li) => li.text().replace(/\s+/g, ' '))
		expect(lines[0]).toBe('A battery 42% · 812 MB free · 2 chunks pending · heartbeat 4s ago · screen awake · foreground · capturing · RECORDING')
		expect(lines[1]).toBe('B battery — · — · — · never heard · — · — · — · no recording')
		expect(localStorage.getItem('citizens-live-advanced')).toBe('1')
	})
})
