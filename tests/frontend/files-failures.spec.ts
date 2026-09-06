// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * A failed table has to say what went wrong and what to do.
 *
 * Failures showed as an orange pill reading TRANSCRIPTION_FAILED or
 * AUDIO_INVALID and nothing else: no reason, no next step. The states differ
 * entirely in what they need — a full disk wants space freeing and a retry,
 * corrupted audio wants the table to record again — so the pill alone left the
 * facilitator with no way to tell those apart.
 *
 * And the retry endpoint added with the ASSEMBLING fix had nothing calling it,
 * so a recording wedged by a full disk still had no route back.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CzFailureNote from '../../frontend/src/components/ui/CzFailureNote.vue'
import FilesTab from '../../frontend/src/components/FilesTab.vue'
import { mountWithI18n } from './support/mount'

const listFiles = vi.fn()
const retryAssembly = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: {
		listFiles: (...a: unknown[]) => listFiles(...a),
		retryAssembly: (...a: unknown[]) => retryAssembly(...a),
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
						state: 'ASSEMBLING',
						mime_type: 'audio/webm',
						duration_seconds: 120,
						size_bytes: 1024,
						sha256: '',
						created_at: null,
						audio_available: true,
						audio_deleted_at: null,
						has_transcript: false,
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
	retryAssembly.mockReset().mockResolvedValue({ state: 'ASSEMBLING' })
})

describe('a wedged recording', () => {
	it('says the disk was full rather than only that it failed', async () => {
		listFiles.mockResolvedValue(
			listing({ error_code: 'STORAGE_FULL', can_retry_assembly: true }),
		)
		const wrapper = mountWithI18n(FilesTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		expect(wrapper.text()).toContain('ran out of space')
		expect(wrapper.text()).toContain('free some space')
	})

	it('offers the retry that the endpoint has always supported', async () => {
		listFiles.mockResolvedValue(
			listing({ error_code: 'STORAGE_FULL', can_retry_assembly: true }),
		)
		const wrapper = mountWithI18n(FilesTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		const retry = wrapper.findAll('button').find((b) => b.text().trim() === 'Retry')
		expect(retry).toBeDefined()

		await retry!.trigger('click')
		expect(retryAssembly).toHaveBeenCalledWith('rec-1')
	})

	it('does not offer a retry for a recording that is fine', async () => {
		listFiles.mockResolvedValue(
			listing({ state: 'READY_FOR_REVIEW', can_retry_assembly: false }),
		)
		const wrapper = mountWithI18n(FilesTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		expect(wrapper.findAll('button').find((b) => b.text().trim() === 'Retry')).toBeUndefined()
	})
})

describe('failure explanations', () => {
	it('distinguishes a recoverable failure from one that needs re-recording', () => {
		const full = mountWithI18n(CzFailureNote, {
			props: { state: 'ASSEMBLING', errorCode: 'STORAGE_FULL' },
		})
		const gone = mountWithI18n(CzFailureNote, {
			props: { state: 'AUDIO_INVALID', errorCode: 'CHUNKS_GONE' },
		})

		expect(full.text()).toContain('still here')
		expect(gone.text()).toContain('record the round again')
	})

	it('falls back to the state when there is no specific code', () => {
		const wrapper = mountWithI18n(CzFailureNote, { props: { state: 'TRANSCRIPTION_FAILED' } })

		expect(wrapper.text()).toContain('tried again')
	})

	it('says nothing at all about a healthy recording', () => {
		const wrapper = mountWithI18n(CzFailureNote, { props: { state: 'READY_FOR_REVIEW' } })

		expect(wrapper.text()).toBe('')
	})
})

describe('the device-audio purge line', () => {
	const CLOSED = { id: 'a1', name: 'Bologna', closed_at: '2026-09-05T10:00:00Z', rounds: [] }

	function withDeviceAudio(over: Record<string, unknown>) {
		const base = listing({})
		return {
			...base,
			device_audio: {
				purge_requested_at: null,
				auto_purge: true,
				devices: 8,
				cleared: 0,
				still_holding: 8,
				unknown: 0,
				...over,
			},
		}
	}

	it('says nothing when no purge was ever requested', async () => {
		// the listing always carries device_audio now; falling back to it
		// unconditionally told every assembly "0 of 8 phones cleared their copy"
		listFiles.mockResolvedValue(withDeviceAudio({ purge_requested_at: null }))
		const wrapper = mountWithI18n(FilesTab, { props: { assembly: CLOSED } })
		await flushPromises()

		expect(wrapper.text()).not.toContain('reported clearing their copy')
	})

	it('shows coverage once a purge has been requested', async () => {
		listFiles.mockResolvedValue(
			withDeviceAudio({ purge_requested_at: '2026-09-05T11:00:00Z', cleared: 6, still_holding: 2 }),
		)
		const wrapper = mountWithI18n(FilesTab, { props: { assembly: CLOSED } })
		await flushPromises()

		expect(wrapper.text()).toContain('6 of 8')
	})
})
