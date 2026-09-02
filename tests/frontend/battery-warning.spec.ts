// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Seeing a phone die before it dies.
 *
 * Everything else about device replacement is recovery. This is the only part
 * that prevents the problem: a facilitator who knows table 3 is at 8% can swap
 * the phone between rounds instead of losing half of one.
 *
 * The caveat matters as much as the feature. Only Chromium exposes the Battery
 * API — Safari and Firefox removed it on fingerprinting grounds — so a table
 * reporting no battery means "unknown", and the UI must never let that read as
 * "fine".
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

function monitorWith(status: Record<string, unknown>) {
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
				number: 1,
				device: { connected: true, seconds_since_contact: 3, status },
				armed: false,
				local_recording_safe: true,
				recording: {
					id: 'rec-1',
					state: 'RECORDING',
					started_at: null,
					received_chunks: 4,
					total_chunks: null,
					error_code: '',
				},
			},
		],
	}
}

beforeEach(() => roundMonitor.mockReset())

describe('the battery warning', () => {
	it('names the level while there is still time to act', async () => {
		roundMonitor.mockResolvedValue(monitorWith({ storage_ok: true, battery_level: 0.08 }))
		const wrapper = mountWithI18n(MonitorTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		expect(wrapper.text()).toContain('battery 8%')
	})

	it('stays quiet on a healthy phone', async () => {
		roundMonitor.mockResolvedValue(monitorWith({ storage_ok: true, battery_level: 0.9 }))
		const wrapper = mountWithI18n(MonitorTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		expect(wrapper.text()).not.toContain('battery')
	})

	it('says nothing at all when the browser will not report it', async () => {
		// Safari and Firefox. Absence must not be shown as a level, and must
		// not be treated as 0% either.
		roundMonitor.mockResolvedValue(monitorWith({ storage_ok: true }))
		const wrapper = mountWithI18n(MonitorTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		expect(wrapper.text()).not.toContain('battery')
	})

	it('shows a storage error ahead of a low battery', async () => {
		// audio that cannot be written is already failing; a low battery is a
		// warning about the future
		roundMonitor.mockResolvedValue(monitorWith({ storage_ok: false, battery_level: 0.05 }))
		const wrapper = mountWithI18n(MonitorTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		expect(wrapper.text()).toContain('storage error')
		expect(wrapper.text()).not.toContain('battery')
	})
})
