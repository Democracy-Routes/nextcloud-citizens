// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The Live tab's "Message the tables" row: presets go out with one click
 * (worded by the server, so the organizer never types "5 minutes left"), a
 * message can go to one table, and the row says who has shown it.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MonitorTab from '../../frontend/src/components/MonitorTab.vue'
import { mountWithI18n } from './support/mount'

const roundMonitor = vi.fn()
const roundMessages = vi.fn()
const sendMessage = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: {
		roundMonitor: (...args: unknown[]) => roundMonitor(...args),
		roundMessages: (...args: unknown[]) => roundMessages(...args),
		sendMessage: (...args: unknown[]) => sendMessage(...args),
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

function table(number: number) {
	return {
		table_id: `t${number}`, number, color_key: 'blue',
		device: { connected: true, seconds_since_contact: 3, status: {} },
		armed: true, local_recording_safe: true, recording: null, superseded_recordings: [],
		recorders: [], readiness: { status: 'READY', reasons: [] },
	}
}

const SENT = {
	id: 3, kind: 'TIME_LEFT', text: '5 minutes left', sound: false, created_at: new Date().toISOString(),
	created_by: 'tester', target_table_number: null, seen_by: [1], not_seen_by: [2],
}

beforeEach(() => {
	roundMonitor.mockReset()
	roundMessages.mockReset()
	sendMessage.mockReset()
	roundMonitor.mockResolvedValue({
		round_id: 'round-1', status: 'ACTIVE', started_at: new Date().toISOString(), duration_minutes: 30,
		recording_mode: 'orchestrated', tables_ready: 2, tables_total: 2, tables: [table(1), table(2)],
		readiness: { status: 'READY', ready: 2, needs_attention: 0, blocked: 0 }, rounds: ASSEMBLY.rounds,
	})
	roundMessages.mockResolvedValue([])
	sendMessage.mockResolvedValue(SENT)
})

describe('Message the tables', () => {
	it('sends a preset to every table with one click and shows who has it', async () => {
		const wrapper = mountWithI18n(MonitorTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()
		const five = wrapper.findAll('.cz-broadcast button').find((b) => b.text() === '5 min left')
		expect(five).toBeTruthy()
		roundMessages.mockResolvedValue([SENT])
		await five!.trigger('click')
		await flushPromises()
		expect(sendMessage).toHaveBeenCalledWith('round-1', {
			kind: 'TIME_LEFT', minutes: 5, target_table_number: null,
		})
		expect(wrapper.find('.cz-broadcast__log').text()).toContain('5 minutes left')
		expect(wrapper.find('.cz-broadcast__delivery').text()).toBe('Delivered 1/2 · Table 2 not yet')
	})

	it('can address one table and write its own words', async () => {
		const wrapper = mountWithI18n(MonitorTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()
		const options = wrapper.findAll('.cz-broadcast__target option')
		expect(options.map((o) => o.text())).toEqual(['all tables', 'Table 1', 'Table 2'])
		await options[2].setSelected()
		await wrapper.findAll('.cz-broadcast button').find((b) => b.text() === 'Write a message')!.trigger('click')
		await wrapper.find('.cz-broadcast input').setValue('Please let the quieter voices speak')
		await wrapper.find('.cz-broadcast form').trigger('submit')
		await flushPromises()
		expect(sendMessage).toHaveBeenCalledWith('round-1', {
			kind: 'CUSTOM', text: 'Please let the quieter voices speak', target_table_number: 2,
		})
		expect((wrapper.find('.cz-broadcast input').element as HTMLInputElement).value).toBe('')
	})
})
