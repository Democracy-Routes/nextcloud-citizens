// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The phone that most needs to hear "clear your copy" is the one that never
 * reloads.
 *
 * The organizer's request travels on a status poll, and the recorder only
 * looked at it when a session was joined or resumed at boot. But at the end of
 * an assembly a phone is sitting on the finished screen, joined hours ago —
 * precisely the phone whose owner is about to walk out with a recording on it,
 * and precisely the one that never checked.
 */
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const status = vi.fn()
const join = vi.fn()
const clearSynchronizedRecordings = vi.fn()

vi.mock('../../frontend/src/recorder/api', async () => {
	const actual = await vi.importActual<Record<string, unknown>>(
		'../../frontend/src/recorder/api',
	)
	return {
		...actual,
		recorderApi: {
			status: (...a: unknown[]) => status(...a),
			join: (...a: unknown[]) => join(...a),
		},
	}
})
vi.mock('../../frontend/src/recorder/engine', () => ({
	RecorderEngine: class {
		state = { phase: 'idle' }
		mediaStream = null
	},
	clearSynchronizedRecordings: (...a: unknown[]) => clearSynchronizedRecordings(...a),
}))
vi.mock('../../frontend/src/recorder/idb', () => ({
	idb: {
		unfinishedRecordings: vi.fn().mockResolvedValue([]),
		getRecordings: vi.fn().mockResolvedValue([]),
		chunksFor: vi.fn().mockResolvedValue([]),
		deleteRecording: vi.fn(),
		countFor: vi.fn().mockResolvedValue(0),
	},
}))
vi.mock('../../frontend/src/recorder/logger', () => ({ initLogger: vi.fn(), clientLog: vi.fn() }))

const RecorderApp = (await import('../../frontend/src/recorder/RecorderApp.vue')).default
const { mountWithI18n } = await import('./support/mount')

const ASSEMBLY = { id: 'a1', name: 'Bologna', language: 'en', recording_mode: 'orchestrated' }

const SESSION = {
	session_token: 'tok',
	expires_at: new Date(Date.now() + 3_600_000).toISOString(),
	assembly: ASSEMBLY,
	table_number: 3,
	rounds: [],
}

let wrapper: ReturnType<typeof mountWithI18n> | null = null

beforeEach(() => {
	vi.useFakeTimers()
	status.mockReset()
	clearSynchronizedRecordings.mockReset().mockResolvedValue(1)
	localStorage.setItem('citizens-recorder-session', JSON.stringify(SESSION))
	window.location.hash = ''
})

afterEach(() => {
	wrapper?.unmount()
	wrapper = null
	localStorage.clear()
	vi.useRealTimers()
})

async function mountJoined() {
	wrapper = mountWithI18n(RecorderApp)
	await flushPromises()
	return wrapper
}

describe('a phone that has been open since the assembly began', () => {
	it('clears itself when the request arrives on a later poll', async () => {
		// joined long ago, when no purge had been asked for
		status.mockResolvedValue({ ...SESSION, purge_local_audio: false })
		await mountJoined()
		expect(clearSynchronizedRecordings).not.toHaveBeenCalled()

		// the organizer closes the session and presses the button
		status.mockResolvedValue({ ...SESSION, purge_local_audio: true })
		await vi.advanceTimersByTimeAsync(35_000)
		await flushPromises()

		expect(clearSynchronizedRecordings).toHaveBeenCalledWith('a1')
	})

	it('tells the person holding it what happened', async () => {
		status.mockResolvedValue({ ...SESSION, purge_local_audio: true })
		await mountJoined()
		await vi.advanceTimersByTimeAsync(35_000)
		await flushPromises()

		// it is their device; doing this silently would be the wrong way round
		expect(wrapper!.text()).toContain('removed from this phone')
	})

	it('keeps asking, so a phone offline at the time still hears', async () => {
		status.mockRejectedValue(new TypeError('Failed to fetch'))
		await mountJoined()
		await vi.advanceTimersByTimeAsync(35_000)

		status.mockResolvedValue({ ...SESSION, purge_local_audio: true })
		await vi.advanceTimersByTimeAsync(35_000)
		await flushPromises()

		expect(clearSynchronizedRecordings).toHaveBeenCalledWith('a1')
	})

	it('does nothing at all until the organizer asks', async () => {
		status.mockResolvedValue({ ...SESSION, purge_local_audio: false })
		await mountJoined()

		await vi.advanceTimersByTimeAsync(120_000)
		await flushPromises()

		expect(clearSynchronizedRecordings).not.toHaveBeenCalled()
	})
})
