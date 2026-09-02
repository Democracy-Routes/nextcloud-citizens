// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The action has to be where the facilitator is already looking.
 *
 * The Live tab had three per-table actions and none of them helped a table
 * whose phone had died — the endpoint that releases it existed but nothing in
 * the UI called it, so in a real room the table waited twenty minutes while
 * the round ran out.
 *
 * It also showed a failure as a bare orange pill. The server has always sent
 * the reason; only the Files tab rendered it.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MonitorTab from '../../frontend/src/components/MonitorTab.vue'
import { mountWithI18n } from './support/mount'

const roundMonitor = vi.fn()
const replaceDevice = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: {
		roundMonitor: (...a: unknown[]) => roundMonitor(...a),
		replaceDevice: (...a: unknown[]) => replaceDevice(...a),
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

function monitor({
	connected = false,
	state = 'RECORDING',
	errorCode = '',
}: { connected?: boolean; state?: string; errorCode?: string } = {}) {
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
				device: { connected, seconds_since_contact: connected ? 3 : 240, status: {} },
				armed: false,
				local_recording_safe: false,
				recording: {
					id: 'rec-1',
					state,
					started_at: null,
					received_chunks: 12,
					total_chunks: null,
					error_code: errorCode,
				},
			},
		],
	}
}

const replaceButton = (wrapper: ReturnType<typeof mountWithI18n>) =>
	wrapper.findAll('button').find((b) => b.text().includes('Replace device'))

beforeEach(() => {
	roundMonitor.mockReset()
	replaceDevice.mockReset().mockResolvedValue({ state: 'UPLOAD_INCOMPLETE', assembling: true })
})

describe('the Replace device action', () => {
	it('appears for a table whose phone has stopped answering', async () => {
		roundMonitor.mockResolvedValue(monitor({ connected: false }))
		const wrapper = mountWithI18n(MonitorTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		expect(replaceButton(wrapper)).toBeDefined()
	})

	it('does not appear while the phone is still answering', async () => {
		roundMonitor.mockResolvedValue(monitor({ connected: true }))
		const wrapper = mountWithI18n(MonitorTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		expect(replaceButton(wrapper)).toBeUndefined()
	})

	it('does not appear once the table has finished recording', async () => {
		// a stale device with a finished recording is a phone somebody closed,
		// not a table that needs rescuing
		roundMonitor.mockResolvedValue(monitor({ connected: false, state: 'TRANSCRIBED' }))
		const wrapper = mountWithI18n(MonitorTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		expect(replaceButton(wrapper)).toBeUndefined()
	})

	it('asks first, and says what happens to the audio already recorded', async () => {
		roundMonitor.mockResolvedValue(monitor({ connected: false }))
		const wrapper = mountWithI18n(MonitorTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		await replaceButton(wrapper)!.trigger('click')

		expect(replaceDevice).not.toHaveBeenCalled()
		expect(wrapper.text()).toContain('same QR code')
	})

	it('releases the table when confirmed', async () => {
		roundMonitor.mockResolvedValue(monitor({ connected: false }))
		const wrapper = mountWithI18n(MonitorTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()
		await replaceButton(wrapper)!.trigger('click')

		await wrapper.find('.cz-modal .cz-btn--danger').trigger('click')
		await flushPromises()

		expect(replaceDevice).toHaveBeenCalledWith('rec-1')
	})
})

describe('why a table failed', () => {
	it('explains the reason instead of showing a bare state', async () => {
		roundMonitor.mockResolvedValue(
			monitor({ connected: false, state: 'ASSEMBLING', errorCode: 'STORAGE_FULL' }),
		)
		const wrapper = mountWithI18n(MonitorTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		expect(wrapper.text()).toContain('ran out of space')
	})

	it('stays quiet about a healthy table', async () => {
		roundMonitor.mockResolvedValue(monitor({ connected: true, state: 'RECORDING' }))
		const wrapper = mountWithI18n(MonitorTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		expect(wrapper.text()).not.toContain('ran out of space')
	})
})
