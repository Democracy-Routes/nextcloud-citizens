// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * R14: a spent single-use code scanned again by the same phone — a reload,
 * a second tap, "Record another session" — must return the session instead
 * of a 410. The phone proves which device it is with a random id kept in
 * localStorage and sent on every join; two joins from the same phone must
 * carry the same id.
 */
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

const join = vi.fn()
const peekCapability = vi.fn()

vi.mock('../../frontend/src/recorder/api', async () => {
	const actual = await vi.importActual<Record<string, unknown>>('../../frontend/src/recorder/api')
	return {
		...actual,
		recorderApi: {
			join: (...a: unknown[]) => join(...a),
			peekCapability: (...a: unknown[]) => peekCapability(...a),
		},
	}
})
vi.mock('../../frontend/src/recorder/engine', () => ({
	RecorderEngine: class {
		state = { phase: 'idle' }
		mediaStream = null
	},
	clearSynchronizedRecordings: vi.fn(),
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
vi.mock('../../frontend/src/recorder/logger', () => ({ initLogger: vi.fn(), clientLog: vi.fn(), ship: vi.fn() }))

const RecorderApp = (await import('../../frontend/src/recorder/RecorderApp.vue')).default
const { mountWithI18n } = await import('./support/mount')

const ASSEMBLY = { id: 'a1', name: 'Bologna', language: 'en', recording_mode: 'independent' }
const DEVICE_PATTERN = /^[A-Za-z0-9_-]{8,64}$/

function sessionFor(token: string) {
	return {
		session_token: token,
		expires_at: new Date(Date.now() + 3_600_000).toISOString(),
		assembly: ASSEMBLY,
		table_number: 1,
		rounds: [],
	}
}

let wrapper: ReturnType<typeof mountWithI18n> | null = null

beforeEach(() => {
	join.mockReset()
	peekCapability.mockReset().mockResolvedValue({ valid: false, reason: 'invalid' })
	localStorage.clear()
	history.replaceState(null, '', '/')
})

afterEach(() => {
	wrapper?.unmount()
	wrapper = null
	localStorage.clear()
	history.replaceState(null, '', '/')
})

it('keeps one random device id across joins and sends it every time', async () => {
	join.mockResolvedValueOnce(sessionFor('s1'))
	history.replaceState(null, '', '/#/join/first-code')
	wrapper = mountWithI18n(RecorderApp)
	await flushPromises()

	expect(join).toHaveBeenCalledTimes(1)
	const [firstToken, firstDevice] = join.mock.calls[0]
	expect(firstToken).toBe('first-code')
	expect(firstDevice).toMatch(DEVICE_PATTERN)
	expect(localStorage.getItem('citizens-recorder-device')).toBe(firstDevice)

	join.mockResolvedValueOnce(sessionFor('s2'))
	history.replaceState(null, '', '/#/join/second-code')
	window.dispatchEvent(new HashChangeEvent('hashchange'))
	await flushPromises()

	expect(join).toHaveBeenCalledTimes(2)
	const [secondToken, secondDevice] = join.mock.calls[1]
	expect(secondToken).toBe('second-code')
	expect(secondDevice).toBe(firstDevice)
})
