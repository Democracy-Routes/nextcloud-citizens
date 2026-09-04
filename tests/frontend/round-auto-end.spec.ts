// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Rounds ended only when a facilitator clicked.
 *
 * Participants reported the consequence rather than the cause: rounds started
 * and ended at different times across tables, which they found unfair and
 * confusing. The timer expired and the app waited.
 *
 * It now ends on time, but through a grace window — a timer that cuts a table
 * off mid-sentence at a civic assembly is worse than a round running a minute
 * long, so the facilitator can extend or take over.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MonitorTab from '../../frontend/src/components/MonitorTab.vue'
import { mountWithI18n } from './support/mount'

const roundMonitor = vi.fn()
const endRound = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: {
		roundMonitor: (...a: unknown[]) => roundMonitor(...a),
		endRound: (...a: unknown[]) => endRound(...a),
		startRound: vi.fn(),
		replaceDevice: vi.fn(),
		roundTranscripts: vi.fn(),
	},
	ApiError: class extends Error {},
	BASE: '',
}))

const ASSEMBLY = {
	id: 'a1',
	name: 'Bologna',
	recording_mode: 'orchestrated',
	rounds: [{ id: 'round-1', position: 1, title: 'Mobility', status: 'ACTIVE' }],
}

/** A round that started `minutesAgo` ago with a 30-minute duration. */
function monitor(minutesAgo: number) {
	return {
		round_id: 'round-1',
		status: 'ACTIVE',
		started_at: new Date(Date.now() - minutesAgo * 60_000).toISOString(),
		duration_minutes: 30,
		recording_mode: 'orchestrated',
		tables_ready: 1,
		tables_total: 1,
		tables: [],
		rounds: [{ id: 'round-1', position: 1, title: 'Mobility', status: 'ACTIVE' }],
	}
}

async function mount(minutesAgo: number) {
	roundMonitor.mockResolvedValue(monitor(minutesAgo))
	const wrapper = mountWithI18n(MonitorTab, { props: { assembly: ASSEMBLY } })
	await flushPromises()
	await vi.advanceTimersByTimeAsync(1100) // let the 1 Hz clock tick once
	return wrapper
}

beforeEach(() => {
	vi.useFakeTimers()
	roundMonitor.mockReset()
	endRound.mockReset().mockResolvedValue({})
})

describe('a round whose time is up', () => {
	it('says nothing while the round is still running', async () => {
		const wrapper = await mount(10)

		expect(wrapper.text()).not.toContain('Time is up')
		expect(endRound).not.toHaveBeenCalled()
	})

	it('shows overrun instead of sitting at 00:00', async () => {
		const wrapper = await mount(31)

		// the countdown used to clamp at zero, so a round an hour over looked
		// like one that had just finished
		expect(wrapper.text()).toMatch(/\+0[01]:/)
	})

	it('offers the facilitator the exception before ending', async () => {
		const wrapper = await mount(30)

		expect(wrapper.text()).toContain('Time is up')
		expect(wrapper.text()).toContain('Extend')
		expect(endRound).not.toHaveBeenCalled()
	})

	it('ends the round once the grace window expires', async () => {
		await mount(30)

		await vi.advanceTimersByTimeAsync(61_000)

		expect(endRound).toHaveBeenCalledWith('round-1')
	})

	it('does not end it when the facilitator extends', async () => {
		const wrapper = await mount(30)
		await wrapper.findAll('button').find((b) => b.text().includes('Extend'))!.trigger('click')

		await vi.advanceTimersByTimeAsync(61_000)

		expect(endRound).not.toHaveBeenCalled()
	})

	it('does not end it when the facilitator says keep going', async () => {
		const wrapper = await mount(30)
		await wrapper.findAll('button').find((b) => b.text().includes('Keep going'))!.trigger('click')

		await vi.advanceTimersByTimeAsync(120_000)

		expect(endRound).not.toHaveBeenCalled()
	})
})
