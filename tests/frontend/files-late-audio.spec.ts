// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The Files tab's record of what the server did without anyone at the
 * table tapping Finish: closed by the 5-minute silence sweep, closed from
 * the Live tab, or — for the continuation row — when its later audio first
 * arrived.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import FilesTab from '../../frontend/src/components/FilesTab.vue'
import { mountWithI18n } from './support/mount'

const listFiles = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: {
		listFiles: (...a: unknown[]) => listFiles(...a),
		retryAssembly: vi.fn(),
		requestTranscription: vi.fn(),
		deleteRecordingAudio: vi.fn(),
		deleteRecordingTranscript: vi.fn(),
		deleteAssemblyAudio: vi.fn(),
		deleteAssemblyTranscripts: vi.fn(),
	},
	ApiError: class extends Error {},
	BASE: '',
}))

function listing(overrides: Record<string, unknown>) {
	return {
		totals: { recordings: 1, audio_bytes: 1024, audio_deleted: 0, kept_past_retention: 0 },
		device_audio: { purge_requested_at: null, auto_purge: true, devices: 0, cleared: 0, still_holding: 0, unknown: 0 },
		rounds: [
			{
				id: 'round-1',
				position: 1,
				title: 'R1',
				tables: [
					{
						recording_id: 'rec-1',
						table_number: 3,
						state: 'READY_FOR_REVIEW',
						mime_type: 'audio/webm',
						duration_seconds: 120,
						size_bytes: 1024,
						sha256: '',
						created_at: '2026-10-13T11:42:00Z',
						audio_available: true,
						audio_deleted_at: null,
						has_transcript: true,
						transcript_source: '',
						can_retranscribe: true,
						...overrides,
					},
				],
			},
		],
	}
}

const ASSEMBLY = { id: 'a1', name: 'Bologna', rounds: [] }

beforeEach(() => {
	listFiles.mockReset()
})

describe('a recording the server closed without anyone tapping Finish', () => {
	it('says it was closed by the silence sweep', async () => {
		listFiles.mockResolvedValue(listing({ closed_by: 'silence' }))
		const wrapper = mountWithI18n(FilesTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		expect(wrapper.find('[data-test="closed-silence"]').text()).toContain('5 min of silence')
	})

	it('says it was closed from the Live tab', async () => {
		listFiles.mockResolvedValue(listing({ closed_by: 'organizer' }))
		const wrapper = mountWithI18n(FilesTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		expect(wrapper.find('[data-test="closed-organizer"]').text()).toContain('Live tab')
	})

	it('says when a continuation row\'s audio arrived', async () => {
		listFiles.mockResolvedValue(listing({ continued_from_id: 'rec-0' }))
		const wrapper = mountWithI18n(FilesTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		const note = wrapper.find('[data-test="audio-added"]')
		expect(note.text()).toContain('audio added at')
		expect(note.text()).toMatch(/\d{1,2}:\d{2}/)
	})

	it('says nothing of this for an ordinary recording', async () => {
		listFiles.mockResolvedValue(listing({}))
		const wrapper = mountWithI18n(FilesTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		expect(wrapper.find('[data-test="closed-silence"]').exists()).toBe(false)
		expect(wrapper.find('[data-test="closed-organizer"]').exists()).toBe(false)
		expect(wrapper.find('[data-test="audio-added"]').exists()).toBe(false)
	})
})
