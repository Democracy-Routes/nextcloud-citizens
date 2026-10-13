// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * R17: what each table phone's own log says about how it behaved, read back
 * from the Files tab after the fact — browser family, chunks saved, hidden
 * windows, gaps, the notable watchdog lines. Loaded on demand (it re-reads
 * every phone's log file on the server), never on the tab's regular poll.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import FilesTab from '../../frontend/src/components/FilesTab.vue'
import { mountWithI18n } from './support/mount'

const listFiles = vi.fn()
const deviceReport = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: {
		listFiles: (...a: unknown[]) => listFiles(...a),
		deviceReport: (...a: unknown[]) => deviceReport(...a),
		retryAssembly: vi.fn(),
		requestTranscription: vi.fn(),
		deleteRecordingAudio: vi.fn(),
		deleteRecordingTranscript: vi.fn(),
		deleteAssemblyAudio: vi.fn(),
		deleteAssemblyTranscripts: vi.fn(),
		purgeDeviceAudio: vi.fn(),
	},
	ApiError: class extends Error {
		status = 0
	},
	BASE: '',
}))

const ASSEMBLY = { id: 'a1', name: 'Bologna', rounds: [] }

const EMPTY_LISTING = {
	totals: { recordings: 0, audio_bytes: 0, audio_deleted: 0, kept_past_retention: 0 },
	device_audio: { purge_requested_at: null, auto_purge: true, devices: 0, cleared: 0, still_holding: 0, unknown: 0 },
	rounds: [],
}

beforeEach(() => {
	listFiles.mockReset().mockResolvedValue(EMPTY_LISTING)
	deviceReport.mockReset()
})

async function openSection(wrapper: Awaited<ReturnType<typeof mountWithI18n>>) {
	await flushPromises()
	await wrapper.find('[data-test="device-report-toggle"]').trigger('click')
}

describe('the phone report', () => {
	it('stays collapsed with nothing loaded until asked', async () => {
		const wrapper = mountWithI18n(FilesTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		expect(wrapper.find('[data-test="device-report-load"]').exists()).toBe(false)
		expect(deviceReport).not.toHaveBeenCalled()
	})

	it('loads the report only once asked, and shows one row per phone', async () => {
		deviceReport.mockResolvedValue({
			sessions: 2,
			with_gaps: 1,
			families: { 'Android Chrome': 1, 'iOS Safari': 1 },
			text: 'plain text report',
			phones: [
				{
					session_id: 's1', table_number: 3, slot: 1,
					first_ts: 1000, last_ts: 2000,
					family: 'Android Chrome', user_agent: 'Mozilla/5.0 (Android)', standalone: true,
					wake_lock: { wake_lock_acquired: 1 },
					hidden_windows: [{ from: 1200, seconds: 60, chunks: 0 }],
					gaps: [{ from: 1300, seconds: 62, seq: 3 }],
					recordings: [{ ts: 1000, id: 'abc12345', mime: 'audio/webm' }],
					chunks: 12,
					upload_failures: 1,
					notable: [{ ts: 1500, event: 'capture_interrupted', data: {} }],
				},
				{
					session_id: 's2', table_number: null, slot: 2,
					first_ts: null, last_ts: null,
					family: 'iOS Safari', user_agent: 'Mozilla/5.0 (iPhone)', standalone: false,
					wake_lock: {},
					hidden_windows: [],
					gaps: [],
					recordings: [],
					chunks: 0,
					upload_failures: 0,
					notable: [],
				},
			],
		})
		const wrapper = mountWithI18n(FilesTab, { props: { assembly: ASSEMBLY } })
		await openSection(wrapper)

		await wrapper.find('[data-test="device-report-load"]').trigger('click')
		await flushPromises()

		expect(deviceReport).toHaveBeenCalledWith('a1')
		expect(wrapper.text()).toContain('2 phones with a log out of 2; 1 with a gap over 15 s')

		const rows = wrapper.findAll('[data-test="device-report-row"]')
		expect(rows).toHaveLength(2)
		expect(rows[0].text()).toContain('Table 3')
		expect(rows[0].text()).toContain('Recorder A')
		expect(rows[0].text()).toContain('Android Chrome')
		expect(rows[0].text()).toContain('installed as app')
		expect(rows[0].text()).toContain('12 chunks saved')
		expect(rows[0].text()).toContain('1 upload failure')
		expect(rows[0].text()).toContain('hidden 60 s, 0 chunks captured')
		expect(rows[0].text()).toContain('gap of 62 s before chunk 3')
		expect(rows[0].text()).toContain('capture_interrupted')

		expect(rows[1].text()).toContain('Recorder B')
		expect(rows[1].text()).not.toContain('Table')
		expect(rows[1].text()).not.toContain('installed as app')
	})

	it('shows the raw text only once asked', async () => {
		deviceReport.mockResolvedValue({
			sessions: 1, with_gaps: 0, families: {}, text: 'the full plain-text report',
			phones: [{
				session_id: 's1', table_number: 1, slot: 1, first_ts: 1, last_ts: 2,
				family: 'desktop Chrome', user_agent: 'ua', standalone: null,
				wake_lock: {}, hidden_windows: [], gaps: [], recordings: [],
				chunks: 3, upload_failures: 0, notable: [],
			}],
		})
		const wrapper = mountWithI18n(FilesTab, { props: { assembly: ASSEMBLY } })
		await openSection(wrapper)
		await wrapper.find('[data-test="device-report-load"]').trigger('click')
		await flushPromises()

		expect(wrapper.text()).not.toContain('the full plain-text report')
		await wrapper.find('[data-test="device-report-text"]').trigger('click')
		expect(wrapper.text()).toContain('the full plain-text report')
	})

	it('says so when no phone has sent a log yet', async () => {
		deviceReport.mockResolvedValue({ sessions: 3, with_gaps: 0, families: {}, text: '', phones: [] })
		const wrapper = mountWithI18n(FilesTab, { props: { assembly: ASSEMBLY } })
		await openSection(wrapper)
		await wrapper.find('[data-test="device-report-load"]').trigger('click')
		await flushPromises()

		expect(wrapper.find('[data-test="device-report-empty"]').text()).toContain('No phone has sent a log yet')
	})
})
