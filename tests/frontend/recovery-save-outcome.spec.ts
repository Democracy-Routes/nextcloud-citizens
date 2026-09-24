// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The recovery screen must say what happened to the audio it was asked to
 * save — not "Download started" whatever the browser did.
 *
 * On the iPhone at the 24 September 2026 rehearsal the tap navigated the tab
 * away from the recorder, and the note underneath had already promised a
 * download. The save now goes through the share sheet where there is one and
 * reports its outcome; a dismissed sheet is not a saved file.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import RecoverySync from '../../frontend/src/recorder/components/RecoverySync.vue'
import type { StoredRecording } from '../../frontend/src/recorder/idb'
import { mountWithI18n } from './support/mount'

const saveBlob = vi.fn()
vi.mock('../../frontend/src/download', () => ({
	saveBlob: (...a: unknown[]) => saveBlob(...a),
	canShareFiles: () => true,
}))

const clientLog = vi.fn()
vi.mock('../../frontend/src/recorder/logger', () => ({
	clientLog: (...a: unknown[]) => clientLog(...a),
	ship: vi.fn().mockResolvedValue(undefined),
}))

vi.mock('../../frontend/src/recorder/idb', () => ({
	idb: {
		chunksFor: vi.fn().mockResolvedValue([
			{ seq: 1, blob: new Blob(['b']) },
			{ seq: 0, blob: new Blob(['a']) },
		]),
		deleteChunksFor: vi.fn(),
		deleteRecording: vi.fn(),
	},
}))

vi.mock('../../frontend/src/recorder/engine', () => ({
	RecorderEngine: class {
		state = {
			phase: 'failed',
			errorKind: 'gone',
			localChunks: 2,
			ackedChunks: 0,
			recordingId: 'rec-1',
			startedAt: 1,
		}
		resumeSync = vi.fn().mockResolvedValue(undefined)
		stop = vi.fn()
	},
	pickMimeType: () => 'audio/webm',
}))

const RECORDING: StoredRecording = {
	recordingId: 'rec-1',
	assemblyId: 'a1',
	roundId: 'round-1',
	tableNumber: 3,
	mimeType: 'audio/mp4',
	startedAt: 1,
	finishedAt: null,
	totalChunks: null,
	serverComplete: false,
}

async function tapSave() {
	const wrapper = mountWithI18n(RecoverySync, { props: { session: null, recording: RECORDING } })
	await flushPromises()
	await wrapper.findAll('button').find((b) => /download audio/i.test(b.text()))!.trigger('click')
	await flushPromises()
	return wrapper
}

beforeEach(() => {
	saveBlob.mockReset()
	clientLog.mockReset()
})

describe('saving recovered audio', () => {
	it('says the file was saved when the share sheet took it', async () => {
		saveBlob.mockResolvedValue('shared')

		const wrapper = await tapSave()

		expect(wrapper.text()).toContain('File saved')
		expect(wrapper.text()).not.toContain('Download started')
	})

	it('keeps the download wording where an anchor download happened', async () => {
		saveBlob.mockResolvedValue('downloaded')

		expect((await tapSave()).text()).toContain('Download started')
	})

	it('says nothing when the person dismissed the share sheet', async () => {
		saveBlob.mockResolvedValue('cancelled')

		const text = (await tapSave()).text()
		expect(text).not.toContain('File saved')
		expect(text).not.toContain('Download started')
	})

	it('says the phone could not save when the share sheet refused, and keeps the page', async () => {
		saveBlob.mockRejectedValue(new DOMException('No activation', 'NotAllowedError'))

		const wrapper = await tapSave()

		expect(wrapper.text()).toContain('could not save the file')
		expect(wrapper.text()).toContain('Keep this page open')
		expect(clientLog).toHaveBeenCalledWith('error', 'audio_save_failed', expect.objectContaining({ name: 'NotAllowedError' }))
	})

	it('hands the share sheet the chunks in order, as one mp4 file named after the table', async () => {
		saveBlob.mockResolvedValue('shared')

		await tapSave()

		const [blob, filename] = saveBlob.mock.calls[0] as [Blob, string]
		expect(filename).toBe('citizens-table-3-rec-1-recovered.m4a')
		expect(blob.type).toBe('audio/mp4')
		expect(await blob.text()).toBe('ab')
		expect(clientLog).toHaveBeenCalledWith(
			'info',
			'audio_save_requested',
			expect.objectContaining({ chunks: 2, share: true }),
		)
	})
})
