// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Every recorder has a row on the Live tab, healthy or not, and a recorder
 * that has finished says when instead of repeating a heartbeat that stopped
 * being news. A table with nothing left to record raises no attention line.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MonitorTab from '../../frontend/src/components/MonitorTab.vue'
import { mountWithI18n } from './support/mount'

const roundMonitor = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: {
		roundMonitor: (...a: unknown[]) => roundMonitor(...a),
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

function monitor(recorders: unknown[], readiness?: unknown) {
	return {
		round_id: 'round-1',
		status: 'ACTIVE',
		started_at: new Date().toISOString(),
		duration_minutes: 30,
		recording_mode: 'orchestrated',
		tables_ready: 1,
		tables_total: 1,
		rounds: [{ id: 'round-1', position: 1, title: 'R1', status: 'ACTIVE' }],
		tables: [
			{
				table_id: 't1',
				number: 2,
				color_key: 'green',
				device: { connected: true, seconds_since_contact: 2, status: {} },
				armed: false,
				local_recording_safe: true,
				recording: null,
				superseded_recordings: [],
				recorders,
				...(readiness ? { readiness } : {}),
			},
		],
		readiness: { status: 'READY', tables: [] },
	}
}

const live = (slot: number, label: string, battery: number) => ({
	slot,
	label,
	connected: true,
	seconds_since_contact: 2,
	status: { battery_level: battery, screen_awake: true, local_chunks: 5, acked_chunks: 5 },
	recording: { id: `rec-${slot}`, state: 'RECORDING', coverage: { percent: 98 } },
})

beforeEach(() => roundMonitor.mockReset())

async function mounted(payload: unknown) {
	roundMonitor.mockResolvedValue(payload)
	const wrapper = mountWithI18n(MonitorTab, { props: { assembly: ASSEMBLY } })
	await flushPromises()
	return wrapper
}

describe('a row per recorder', () => {
	it('shows two healthy recorders with letter, connection, battery, state and coverage', async () => {
		const wrapper = await mounted(monitor([live(1, 'A', 0.82), live(2, 'B', 0.5)]))
		const rows = wrapper.findAll('[data-test="recorder-row"]')
		expect(rows).toHaveLength(2)
		expect(rows[0].text()).toContain('A')
		expect(rows[0].text()).toContain('connected')
		expect(rows[0].text()).toContain('82%')
		expect(rows[0].text()).toContain('recording')
		expect(rows[0].text()).toContain('98 %')
		expect(rows[1].text()).toContain('B')
		expect(rows[1].text()).toContain('50%')
	})

	it('tells a finished recorder by its end time, not by its stale heartbeat', async () => {
		const finishedAt = new Date(2026, 9, 25, 14, 7).toISOString()
		const wrapper = await mounted(monitor([{
			slot: 1,
			label: 'A',
			connected: false,
			seconds_since_contact: 100,
			status: { battery_level: 0.1, local_chunks: 9, acked_chunks: 2 },
			finished: true,
			finished_at: finishedAt,
			recording: { id: 'rec-1', state: 'READY_FOR_REVIEW', coverage: { percent: 99 } },
		}]))
		const row = wrapper.find('[data-test="recorder-row"]')
		expect(row.text()).toMatch(/finished \d{1,2}[:.]07/)
		expect(row.text()).toContain('99 %')
		expect(row.text()).not.toContain('ago')
		expect(row.text()).not.toContain('10%')
		expect(row.text()).not.toContain('pending')
		expect(row.classes()).not.toContain('cz-recrow--bad')
	})

	it('raises no attention line for a table with nothing left to record', async () => {
		const wrapper = await mounted(monitor(
			[{
				slot: 1, label: 'A', connected: false, seconds_since_contact: 300, status: { battery_level: 0.05 },
				finished: true, finished_at: new Date().toISOString(),
				recording: { id: 'rec-1', state: 'READY_FOR_REVIEW' },
			}],
			{ status: 'READY', reasons: [] },
		))
		expect(wrapper.text()).not.toContain('needs attention')
		expect(wrapper.text()).not.toContain('need attention')
	})
})
