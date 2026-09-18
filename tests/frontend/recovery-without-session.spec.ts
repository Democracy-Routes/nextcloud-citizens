// SPDX-License-Identifier: AGPL-3.0-or-later
import { flushPromises } from '@vue/test-utils'
import { reactive } from 'vue'
import { afterEach, expect, it, vi } from 'vitest'
import RecorderApp from '../../frontend/src/recorder/RecorderApp.vue'
import RecoverySync from '../../frontend/src/recorder/components/RecoverySync.vue'
import { RecorderApiError, recorderApi } from '../../frontend/src/recorder/api'
import { idb } from '../../frontend/src/recorder/idb'
import { mountWithI18n } from './support/mount'

vi.mock('../../frontend/src/recorder/logger', () => ({ initLogger: vi.fn(), clientLog: vi.fn() }))
const resume = vi.hoisted(() => vi.fn())
const stop = vi.hoisted(() => vi.fn())
vi.mock('../../frontend/src/recorder/engine', async () => ({
	RecorderEngine: class {
		state = reactive({ phase: 'idle', localChunks: 0, ackedChunks: 0 })
		resumeSync = resume
		stop = stop
	},
	clearSynchronizedRecordings: vi.fn(), pickMimeType: () => 'audio/webm',
}))
const recording = { recordingId: 'rec', assemblyId: 'a1', roundId: 'round', tableNumber: 1,
	mimeType: 'audio/webm', startedAt: 1, finishedAt: 2, totalChunks: 1, serverComplete: false }
const session = { session_token: 'expired', table_number: 1,
	assembly: { id: 'a1', name: 'Assembly', language: 'en', recording_mode: 'orchestrated' }, rounds: [] }

afterEach(() => {
	vi.restoreAllMocks()
	vi.clearAllMocks()
	localStorage.clear()
	history.replaceState(null, '', '/')
})

it('expired session still exposes stored audio and skips empty metadata', async () => {
	localStorage.setItem('citizens-recorder-session', JSON.stringify(session))
	vi.spyOn(recorderApi, 'status').mockRejectedValue(new RecorderApiError(401, 'expired'))
	vi.spyOn(idb, 'unfinishedRecordings').mockResolvedValue([{ ...recording, recordingId: 'empty' }, recording])
	vi.spyOn(idb, 'chunksFor').mockImplementation(async (id) => id === 'empty' ? [] : [{ seq: 0, blob: new Blob(['audio']) }] as never)
	const wrapper = mountWithI18n(RecorderApp)
	await flushPromises()
	expect(wrapper.findComponent(RecoverySync).exists()).toBe(true)
	expect(wrapper.text()).toContain('Scan a current QR code')
	expect(wrapper.text()).toContain('Download audio file')
	expect(resume).not.toHaveBeenCalled()
	expect(localStorage.getItem('citizens-recorder-session')).toBeNull()
	await wrapper.findAll('button').find((b) => b.text() === 'Skip for now')!.trigger('click')
	await flushPromises()
	expect(wrapper.findComponent(RecoverySync).exists()).toBe(false)
	expect(wrapper.text().length).toBeGreaterThan(20)
	expect(stop).toHaveBeenCalled()
	wrapper.unmount()
})

it('a matching new session resumes the original recording', async () => {
	const wrapper = mountWithI18n(RecoverySync, { props: { session, recording } })
	await flushPromises()
	expect(resume).toHaveBeenCalledWith('expired', recording)
	wrapper.unmount()
	expect(stop).toHaveBeenCalledTimes(1)
})

it('a QR fragment opened in the same recovery tab joins again without a reload', async () => {
	vi.spyOn(idb, 'unfinishedRecordings').mockResolvedValue([recording])
	vi.spyOn(idb, 'chunksFor').mockResolvedValue([{ seq: 0, blob: new Blob(['audio']) }] as never)
	vi.spyOn(recorderApi, 'join').mockResolvedValue({ ...session, session_token: 'fresh' } as never)
	const wrapper = mountWithI18n(RecorderApp)
	await flushPromises()
	expect(wrapper.text()).toContain('Scan a current QR code')
	history.replaceState(null, '', '/#/join/new-qr')
	window.dispatchEvent(new HashChangeEvent('hashchange'))
	await flushPromises()
	expect(recorderApi.join).toHaveBeenCalledWith('new-qr')
	expect(resume).toHaveBeenCalledWith('fresh', expect.objectContaining({ recordingId: 'rec' }))
	expect(window.location.hash).toBe('')
	wrapper.unmount()
})
