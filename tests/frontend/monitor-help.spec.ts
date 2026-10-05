// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * A table's raised hand on the Live tab: the row stays in view with what the
 * table asked for, and Acknowledge tells the server — which tells the phone.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MonitorTab from '../../frontend/src/components/MonitorTab.vue'
import { mountWithI18n } from './support/mount'

const roundMonitor = vi.fn()
const acknowledgeHelp = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: {
		roundMonitor: (...args: unknown[]) => roundMonitor(...args),
		acknowledgeHelp: (...args: unknown[]) => acknowledgeHelp(...args),
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

const HAND = {
	id: 'h1', kind: 'PROCESS', table_number: 2, slot: 1,
	created_at: new Date().toISOString(), acknowledged_at: null,
}

function table(number: number, help: typeof HAND | null) {
	return {
		table_id: `t${number}`, number, color_key: 'blue',
		device: { connected: true, seconds_since_contact: 3, status: { recording_active: true, storage_ok: true, capture_ok: true } },
		armed: false, local_recording_safe: true,
		recording: { id: `rec${number}`, state: 'RECORDING', started_at: new Date().toISOString(),
			received_chunks: 10, total_chunks: null, error_code: '' },
		superseded_recordings: [],
		recorders: [{ slot: 1, label: 'A', connected: true, seconds_since_contact: 3, status: {}, recording: { id: `rec${number}`, state: 'RECORDING', live_source: true } }],
		help_request: help,
		readiness: help
			? { status: 'NEEDS_ATTENTION', reasons: [{ code: 'HELP_REQUESTED', severity: 'warning', slot: null, data: { kind: help.kind } }] }
			: { status: 'READY', reasons: [] },
	}
}

beforeEach(() => {
	roundMonitor.mockReset()
	acknowledgeHelp.mockReset()
	acknowledgeHelp.mockResolvedValue({ ...HAND, acknowledged_at: new Date().toISOString() })
	roundMonitor.mockResolvedValue({
		round_id: 'round-1', status: 'ACTIVE', started_at: new Date().toISOString(), duration_minutes: 30,
		recording_mode: 'orchestrated', tables_ready: 0, tables_total: 2,
		tables: [table(1, null), table(2, HAND)],
		readiness: { status: 'NEEDS_ATTENTION', ready: 1, needs_attention: 1, blocked: 0 }, rounds: ASSEMBLY.rounds,
	})
})

describe('a raised hand on the Live tab', () => {
	it('keeps the table in view with what it asked for, and Acknowledge tells the server', async () => {
		const wrapper = mountWithI18n(MonitorTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()
		expect(wrapper.text()).toContain('1 table needs attention')
		expect(wrapper.find('.cz-reasons').text()).toBe('the table asks for help — question about the process')
		const ack = wrapper.findAll('button').find((b) => b.text() === 'Acknowledge')
		expect(ack).toBeTruthy()
		await ack!.trigger('click')
		await flushPromises()
		expect(acknowledgeHelp).toHaveBeenCalledWith('h1')
	})
})
