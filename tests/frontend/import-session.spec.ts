// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Importing a session export: the archive goes up in parts, the server builds
 * the assembly, and the organizer sees what came across before opening it.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ImportSessionDialog from '../../frontend/src/components/ImportSessionDialog.vue'
import { mountWithI18n } from './support/mount'

const importSession = vi.fn()
const uploadFile = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: { importSession: (...a: unknown[]) => importSession(...a) },
	ApiError: class extends Error {},
	BASE: '',
}))
vi.mock('../../frontend/src/upload', () => ({
	uploadFile: (...a: unknown[]) => uploadFile(...a),
}))

const result = {
	assembly_id: 'a-9', name: 'Milan Mobility', rounds: 2, tables: 5, recordings: 9,
	transcripts: 8, audio_files: 7, analysis_queued: false, skipped: ['3 audio files were over the size limit'],
}

async function choose(wrapper: ReturnType<typeof mountWithI18n>): Promise<void> {
	const input = wrapper.find('[data-test="import-file"]')
	const file = new File(['zip'], 'export.zip', { type: 'application/zip' })
	Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
	await input.trigger('change')
}

beforeEach(() => {
	importSession.mockReset()
	uploadFile.mockReset().mockImplementation(async (_f: File, _k: string, onProgress?: (n: number) => void) => {
		onProgress?.(0.5)
		return { upload_id: 'u1', size_bytes: 3, sha256: 'x' }
	})
})

describe('the import dialog', () => {
	it('cannot be submitted before a file is chosen', async () => {
		const wrapper = mountWithI18n(ImportSessionDialog)
		expect(wrapper.find('[data-test="import-submit"]').attributes('disabled')).toBeDefined()
		await choose(wrapper)
		expect(wrapper.find('[data-test="import-submit"]').attributes('disabled')).toBeUndefined()
		expect(wrapper.find('[data-test="import-file-info"]').text()).toContain('export.zip')
	})

	it('uploads, imports with the name and merges, and shows what came across', async () => {
		importSession.mockResolvedValue(result)
		const wrapper = mountWithI18n(ImportSessionDialog)
		await choose(wrapper)
		await wrapper.find('[data-test="import-name"]').setValue('  Renamed  ')
		await wrapper.find('[data-test="import-merge-add"]').trigger('click')
		const [from, into] = wrapper.findAll('[data-test="import-merge-row"] input')
		await from.setValue('6')
		await into.setValue('2')
		await wrapper.find('[data-test="import-submit"]').trigger('click')
		await flushPromises()

		expect(uploadFile.mock.calls[0][1]).toBe('session_export')
		expect(importSession).toHaveBeenCalledWith({
			upload_id: 'u1', name: 'Renamed', merge_tables: [{ from: 6, into: 2 }],
		})
		const text = wrapper.find('[data-test="import-result"]').text()
		expect(text).toContain('Milan Mobility')
		expect(text).toContain('2 rounds')
		expect(text).toContain('5 tables')
		expect(text).toContain('9 recordings')
		expect(text).toContain('8 transcripts')
		expect(text).toContain('7 audio files')
		expect(text).toContain('No analysis provider is configured')
		expect(text).toContain('3 audio files were over the size limit')

		await wrapper.find('[data-test="import-open-assembly"]').trigger('click')
		expect(wrapper.emitted('openAssembly')?.[0]).toEqual(['a-9'])
	})

	it('shows the error and stays open so the organizer can retry', async () => {
		importSession.mockRejectedValue(new Error('Not a session export'))
		const wrapper = mountWithI18n(ImportSessionDialog)
		await choose(wrapper)
		await wrapper.find('[data-test="import-submit"]').trigger('click')
		await flushPromises()

		expect(wrapper.find('[data-test="import-error"]').text()).toContain('Not a session export')
		expect(wrapper.find('[data-test="import-result"]').exists()).toBe(false)
		expect(wrapper.emitted('close')).toBeUndefined()
		expect(wrapper.find('[data-test="import-submit"]').attributes('disabled')).toBeUndefined()
	})

	it('adds and removes merge rows', async () => {
		const wrapper = mountWithI18n(ImportSessionDialog)
		await wrapper.find('[data-test="import-merge-add"]').trigger('click')
		await wrapper.find('[data-test="import-merge-add"]').trigger('click')
		expect(wrapper.findAll('[data-test="import-merge-row"]')).toHaveLength(2)
		await wrapper.find('[data-test="import-merge-remove"]').trigger('click')
		expect(wrapper.findAll('[data-test="import-merge-row"]')).toHaveLength(1)
	})
})
