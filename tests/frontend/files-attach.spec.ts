// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Recovering a table by hand from the Files tab: attach a finished audio
 * file or a transcript made elsewhere, or replace an existing transcript. */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import FilesTab from '../../frontend/src/components/FilesTab.vue'
import { ApiError } from '../../frontend/src/api'
import { mountWithI18n } from './support/mount'

const listFiles = vi.fn()
const attachAudio = vi.fn()
const attachTranscript = vi.fn()
const uploadFile = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: {
		listFiles: (...a: unknown[]) => listFiles(...a),
		attachAudio: (...a: unknown[]) => attachAudio(...a),
		attachTranscript: (...a: unknown[]) => attachTranscript(...a),
		retryAssembly: vi.fn(),
		requestTranscription: vi.fn(),
		deleteRecordingAudio: vi.fn(),
		deleteRecordingTranscript: vi.fn(),
		deleteAssemblyAudio: vi.fn(),
		deleteAssemblyTranscripts: vi.fn(),
	},
	ApiError: class extends Error {
		status: number
		constructor(status: number, message: string) {
			super(message)
			this.status = status
		}
	},
	BASE: '',
}))

vi.mock('../../frontend/src/upload', () => ({
	uploadFile: (...a: unknown[]) => uploadFile(...a),
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

async function mountTab(overrides: Record<string, unknown>) {
	listFiles.mockResolvedValue(listing(overrides))
	const wrapper = mountWithI18n(FilesTab, { props: { assembly: ASSEMBLY } })
	await flushPromises()
	return wrapper
}

async function chooseFile(wrapper: ReturnType<typeof mountWithI18n>, file: File) {
	const input = wrapper.find('[data-test="attach-input"]')
	Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
	await input.trigger('change')
	await flushPromises()
}

beforeEach(() => {
	listFiles.mockReset()
	attachAudio.mockReset()
	attachTranscript.mockReset()
	uploadFile.mockReset()
	uploadFile.mockImplementation(async (_f: File, _k: string, onProgress?: (n: number) => void) => {
		onProgress?.(0.42)
		return { upload_id: 'up-1', size_bytes: 3, sha256: 'x' }
	})
})

describe('attaching files to a recording', () => {
	it('offers both attach actions on a failed row', async () => {
		const wrapper = await mountTab({ state: 'AUDIO_INVALID', has_transcript: false, audio_available: false })
		expect(wrapper.find('[data-test="attach-audio"]').exists()).toBe(true)
		expect(wrapper.find('[data-test="attach-transcript"]').exists()).toBe(true)
		expect(wrapper.find('[data-test="replace-transcript"]').exists()).toBe(false)
	})

	it('offers only Replace transcript on a finished row', async () => {
		const wrapper = await mountTab({})
		expect(wrapper.find('[data-test="attach-audio"]').exists()).toBe(false)
		expect(wrapper.find('[data-test="attach-transcript"]').exists()).toBe(false)
		expect(wrapper.find('[data-test="replace-transcript"]').exists()).toBe(true)
	})

	it('uploads a chosen audio file, attaches it and reloads the listing', async () => {
		attachAudio.mockResolvedValue({ recording_id: 'rec-1', state: 'AUDIO_READY', segments: null, duration_seconds: 5, transcription_queued: true, analysis_queued: false })
		const wrapper = await mountTab({ state: 'AUDIO_INVALID', has_transcript: false })
		await wrapper.find('[data-test="attach-audio"]').trigger('click')
		const file = new File(['abc'], 'table3.m4a', { type: 'audio/mp4' })
		await chooseFile(wrapper, file)

		expect(uploadFile).toHaveBeenCalledWith(file, 'audio', expect.any(Function))
		expect(attachAudio).toHaveBeenCalledWith('rec-1', 'up-1', 'audio/mp4')
		expect(listFiles).toHaveBeenCalledTimes(2)
	})

	it('shows the server message when attaching a transcript fails', async () => {
		attachTranscript.mockRejectedValue(new ApiError(422, 'Not a transcript file'))
		const wrapper = await mountTab({ state: 'TRANSCRIPTION_FAILED', has_transcript: false })
		await wrapper.find('[data-test="attach-transcript"]').trigger('click')
		await chooseFile(wrapper, new File(['{}'], 't.json', { type: 'application/json' }))

		expect(uploadFile).toHaveBeenCalledWith(expect.any(File), 'transcript', expect.any(Function))
		expect(wrapper.text()).toContain('Not a transcript file')
		expect(wrapper.find('[data-test="attach-progress"]').exists()).toBe(false)
		expect(wrapper.find('[data-test="attach-transcript"]').attributes('disabled')).toBeUndefined()
	})

	it('asks for confirmation before replacing a transcript', async () => {
		const wrapper = await mountTab({})
		await wrapper.find('[data-test="replace-transcript"]').trigger('click')

		expect(wrapper.text()).toContain('evidence links')
		expect(uploadFile).not.toHaveBeenCalled()
	})
})
