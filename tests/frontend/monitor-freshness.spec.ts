// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The Live tab must act on what the server says now.
 *
 * It polled every four seconds but computed "which round comes next" from the
 * assembly object it was handed on mount, which nothing refreshed. So the card
 * could offer to start a round the server had already started — the
 * facilitator clicks it and gets an error, mid-event, with tables waiting.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MonitorTab from '../../frontend/src/components/MonitorTab.vue'
import { mountWithI18n } from './support/mount'

const roundMonitor = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: {
		roundMonitor: (...args: unknown[]) => roundMonitor(...args),
		startRound: vi.fn(),
		endRound: vi.fn(),
		requestTranscription: vi.fn(),
		recordingTranscript: vi.fn(),
		deviceLogs: vi.fn(),
	},
	ApiError: class extends Error {},
	BASE: '',
}))

/** Round 1 finished; round 2 is ALREADY ACTIVE on the server. */
const MONITOR = {
	round_id: 'round-1',
	status: 'ENDED',
	started_at: null,
	duration_minutes: 30,
	recording_mode: 'orchestrated',
	tables_ready: 2,
	tables_total: 2,
	tables: [],
	rounds: [
		{ id: 'round-1', position: 1, title: 'R1', status: 'ENDED' },
		{ id: 'round-2', position: 2, title: 'R2', status: 'ACTIVE' },
	],
}

/** What the tab was handed on mount, before round 2 was started elsewhere. */
const STALE_ASSEMBLY = {
	id: 'a1',
	name: 'Bologna',
	recording_mode: 'orchestrated',
	rounds: [
		{ id: 'round-1', position: 1, title: 'R1', status: 'ENDED' },
		{ id: 'round-2', position: 2, title: 'R2', status: 'NOT_STARTED' },
	],
}

beforeEach(() => {
	roundMonitor.mockReset().mockResolvedValue(MONITOR)
})

describe('the next-round card', () => {
	it('does not offer a round the server has already started', async () => {
		const wrapper = mountWithI18n(MonitorTab, { props: { assembly: STALE_ASSEMBLY } })
		await flushPromises()

		expect(wrapper.text()).not.toContain('Start Round 2')
	})

	it('offers a round that really is still waiting', async () => {
		roundMonitor.mockResolvedValue({
			...MONITOR,
			rounds: [
				{ id: 'round-1', position: 1, title: 'R1', status: 'ENDED' },
				{ id: 'round-2', position: 2, title: 'R2', status: 'NOT_STARTED' },
			],
		})
		const wrapper = mountWithI18n(MonitorTab, { props: { assembly: STALE_ASSEMBLY } })
		await flushPromises()

		expect(wrapper.text()).toContain('Round 2')
	})

	it('tells the rest of the app when it sees the round change state', async () => {
		const wrapper = mountWithI18n(MonitorTab, { props: { assembly: STALE_ASSEMBLY } })
		await flushPromises()

		roundMonitor.mockResolvedValue({ ...MONITOR, status: 'PROCESSING' })
		await (wrapper.vm as unknown as { polling: { refresh: () => Promise<void> } }).polling.refresh()
		await flushPromises()

		// otherwise the header pill, the sidebar and the Rounds tab stay on
		// whatever they last heard
		expect(wrapper.emitted('changed')).toBeTruthy()
	})
})

describe('freshness', () => {
	it('shows when the view was last current', async () => {
		const wrapper = mountWithI18n(MonitorTab, { props: { assembly: STALE_ASSEMBLY } })
		await flushPromises()

		expect(wrapper.text()).toMatch(/Updated \d{2}:\d{2}:\d{2}/)
	})

	it('says so when it can no longer reach the server', async () => {
		const wrapper = mountWithI18n(MonitorTab, { props: { assembly: STALE_ASSEMBLY } })
		await flushPromises()

		roundMonitor.mockRejectedValue(new TypeError('Failed to fetch'))
		await (wrapper.vm as unknown as { polling: { refresh: () => Promise<void> } }).polling.refresh()
		await flushPromises()

		// the numbers on screen are now history, and must not read as current
		expect(wrapper.text()).toContain('Reconnecting')
	})
})
