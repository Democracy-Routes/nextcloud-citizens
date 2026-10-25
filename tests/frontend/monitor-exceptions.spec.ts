// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The Live tab is exception-first: one line says whether the room is fine,
 * healthy tables fold into a single row, and the tables that need a hand stay
 * in view with the server's reasons worded and the fix beside them. A server
 * without readiness (older than 0.7) folds nothing.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MonitorTab from '../../frontend/src/components/MonitorTab.vue'
import { mountWithI18n } from './support/mount'

const roundMonitor = vi.fn()
const play = vi.fn()

vi.mock('../../frontend/src/recorder/sounds', () => ({
	play: (...args: unknown[]) => play(...args),
}))

vi.mock('../../frontend/src/api', () => ({
	api: {
		roundMonitor: (...args: unknown[]) => roundMonitor(...args),
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

function table(number: number, readiness: unknown, overrides: Record<string, unknown> = {}) {
	return {
		table_id: `t${number}`, number, color_key: 'blue',
		device: { connected: true, seconds_since_contact: 3, status: { recording_active: true, storage_ok: true, capture_ok: true } },
		armed: false, local_recording_safe: true,
		recording: { id: `rec${number}`, state: 'RECORDING', started_at: new Date().toISOString(),
			received_chunks: 10, total_chunks: null, error_code: '' },
		superseded_recordings: [],
		recorders: [{ slot: 1, label: 'A', connected: true, seconds_since_contact: 3, status: {}, recording: { id: `rec${number}`, state: 'RECORDING', live_source: true } }],
		readiness,
		...overrides,
	}
}

const READY = { status: 'READY', reasons: [] }
const OFFLINE = { status: 'BLOCKED', reasons: [{ code: 'RECORDER_OFFLINE', severity: 'blocker', slot: 1, data: { seconds_since_contact: 300 } }] }
const BATTERY = { status: 'NEEDS_ATTENTION', reasons: [{ code: 'LOW_BATTERY', severity: 'warning', slot: 1, data: { battery_level: 0.1 } }] }

function monitor(tables: unknown[], readiness: unknown) {
	return {
		round_id: 'round-1', status: 'ACTIVE', started_at: new Date().toISOString(), duration_minutes: 30,
		recording_mode: 'orchestrated', tables_ready: 0, tables_total: tables.length, tables,
		rounds: [{ id: 'round-1', position: 1, title: 'R1', status: 'ACTIVE' }], readiness,
	}
}

beforeEach(() => roundMonitor.mockReset())

describe('the exception-first Live tab', () => {
	it('folds healthy tables and keeps the ones needing a hand, with reasons and the fix', async () => {
		roundMonitor.mockResolvedValue(monitor(
			[
				table(1, READY), table(2, READY),
				table(3, OFFLINE, { device: { connected: false, seconds_since_contact: 300, status: {} } }),
				table(4, BATTERY, { device: { connected: true, seconds_since_contact: 2, status: { battery_level: 0.1, storage_ok: true } } }),
			],
			{ status: 'BLOCKED', ready: 2, needs_attention: 1, blocked: 1 },
		))
		const wrapper = mountWithI18n(MonitorTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		expect(wrapper.find('.cz-health').text()).toContain('2 tables need attention · 1 cannot record.')
		expect(wrapper.find('.cz-health').classes()).toContain('cz-health--bad')
		expect(wrapper.find('.cz-quietrow').text()).toContain('2 tables running normally')
		// only tables 3 and 4 are rows
		const numbers = wrapper.findAll('tbody tr:not(.cz-quietrow) .cz-posbadge').map((b) => b.text())
		expect(numbers).toEqual(['3', '4'])
		expect(wrapper.text()).toContain('phone not answering')
		expect(wrapper.text()).toContain('battery low — ask the table for a backup phone')
		expect(wrapper.find('.cz-reasons__blocker').exists()).toBe(true)
		// the fix sits in the row: hand the table over for the silent phone
		expect(wrapper.findAll('button').some((b) => b.text().includes('Hand over table'))).toBe(true)

		// the folded tables can be shown on demand
		await wrapper.find('.cz-quietrow button').trigger('click')
		const all = wrapper.findAll('tbody tr:not(.cz-quietrow) .cz-posbadge').map((b) => b.text())
		expect(all).toEqual(['1', '2', '3', '4'])
	})

	it('says everything is fine when it is', async () => {
		roundMonitor.mockResolvedValue(monitor(
			[table(1, READY), table(2, READY)],
			{ status: 'READY', ready: 2, needs_attention: 0, blocked: 0 },
		))
		const wrapper = mountWithI18n(MonitorTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		expect(wrapper.find('.cz-health').text()).toContain('Everything is running normally.')
		expect(wrapper.find('.cz-health').classes()).toContain('cz-health--ok')
		expect(wrapper.findAll('tbody tr:not(.cz-quietrow)')).toHaveLength(0)
		expect(wrapper.find('.cz-quietrow').text()).toContain('2 tables running normally')
	})

	it('still shows a READY table whose own pills have something to say', async () => {
		// the server judged it fine a second ago; the heartbeat now says the
		// microphone went quiet — the row must not be hidden
		roundMonitor.mockResolvedValue(monitor(
			[table(1, READY, { device: { connected: true, seconds_since_contact: 2, status: { recording_active: true, capture_ok: false, storage_ok: true } } })],
			{ status: 'READY', ready: 1, needs_attention: 0, blocked: 0 },
		))
		const wrapper = mountWithI18n(MonitorTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		expect(wrapper.findAll('tbody tr:not(.cz-quietrow)')).toHaveLength(1)
		expect(wrapper.text()).toContain('capture interrupted')
	})

	it('folds nothing for a server that sends no readiness', async () => {
		roundMonitor.mockResolvedValue({ ...monitor([table(1, undefined), table(2, undefined)], undefined), readiness: undefined })
		const wrapper = mountWithI18n(MonitorTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		expect(wrapper.find('.cz-health').exists()).toBe(false)
		expect(wrapper.find('.cz-quietrow').exists()).toBe(false)
		expect(wrapper.findAll('tbody tr')).toHaveLength(2)
	})

	it('words a recorder the server hears nothing from, and rings once when it is new', async () => {
		play.mockReset()
		const SILENT = {
			status: 'BLOCKED',
			reasons: [{ code: 'CAPTURE_SILENT', severity: 'blocker', slot: 1, data: { silent_seconds: 47 } }],
		}
		roundMonitor.mockResolvedValue(monitor(
			[table(1, READY), table(2, READY)],
			{ status: 'READY', ready: 2, needs_attention: 0, blocked: 0 },
		))
		const wrapper = mountWithI18n(MonitorTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()
		expect(play).not.toHaveBeenCalled()
		expect(wrapper.find('[data-test="sound"]').text()).toBe('Sound on')

		// the next poll: table 2 has gone silent — one tone, the reason worded with the seconds
		roundMonitor.mockResolvedValue(monitor(
			[table(1, READY), table(2, SILENT)],
			{ status: 'BLOCKED', ready: 1, needs_attention: 0, blocked: 1 },
		))
		await (wrapper.vm as unknown as { poll: () => Promise<void> }).poll?.()
		await vi.waitFor(() => expect(wrapper.text()).toContain('no audio has reached the server for 47 s'))
		expect(wrapper.text()).toContain('(recorder A)')
		expect(play).toHaveBeenCalledTimes(1)
		expect(play).toHaveBeenCalledWith('alert', 'normal')

		// the same alarm on the following poll does not ring again
		await (wrapper.vm as unknown as { poll: () => Promise<void> }).poll?.()
		await flushPromises()
		expect(play).toHaveBeenCalledTimes(1)

		// sound off: a new alarm stays silent
		await wrapper.find('[data-test="sound"]').trigger('click')
		expect(wrapper.find('[data-test="sound"]').text()).toBe('Sound off')
		roundMonitor.mockResolvedValue(monitor(
			[table(1, SILENT), table(2, SILENT)],
			{ status: 'BLOCKED', ready: 0, needs_attention: 0, blocked: 2 },
		))
		await (wrapper.vm as unknown as { poll: () => Promise<void> }).poll?.()
		await flushPromises()
		expect(play).toHaveBeenCalledTimes(1)
	})

	it('shows each recorder\'s coverage on the row and keeps a sleeping phone in view', async () => {
		const sleepy = table(2, READY, {
			recorders: [
				{ slot: 1, label: 'A', connected: true, seconds_since_contact: 3, status: {},
					recording: { id: 'rec2', state: 'RECORDING', live_source: true, coverage: { audio_seconds: 140, wall_seconds: 600, percent: 23 } } },
				{ slot: 2, label: 'B', connected: true, seconds_since_contact: 2, status: {},
					recording: { id: 'rec2b', state: 'RECORDING', live_source: false, coverage: { audio_seconds: 600, wall_seconds: 600, percent: 100 } } },
			],
		})
		roundMonitor.mockResolvedValue(monitor(
			[table(1, READY), sleepy],
			{ status: 'READY', ready: 2, needs_attention: 0, blocked: 0 },
		))
		const wrapper = mountWithI18n(MonitorTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()
		// table 2 is READY for the server, but a 23 % recorder is not quiet
		const numbers = wrapper.findAll('tbody tr:not(.cz-quietrow) .cz-posbadge').map((b) => b.text())
		expect(numbers).toEqual(['2'])
		const badges = wrapper.findAll('[data-test="coverage"] .cz-coverage')
		expect(badges.map((b) => b.text())).toEqual(['A 23 %', 'B 100 %'])
		expect(badges[0].classes()).toContain('cz-coverage--low')
		expect(badges[1].classes()).not.toContain('cz-coverage--low')
	})

	it('words a refusal seated at the table as the blocker it is', async () => {
		const REFUSED = { status: 'BLOCKED', reasons: [{ code: 'PARTICIPANT_REFUSED', severity: 'blocker', slot: null, data: {} }] }
		roundMonitor.mockResolvedValue(monitor(
			[table(1, REFUSED)],
			{ status: 'BLOCKED', ready: 0, needs_attention: 0, blocked: 1 },
		))
		const wrapper = mountWithI18n(MonitorTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()
		expect(wrapper.text()).toContain('someone seated here refused to be recorded')
		expect(wrapper.find('.cz-reasons__blocker').exists()).toBe(true)
	})

})
