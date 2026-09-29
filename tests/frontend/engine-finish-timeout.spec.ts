// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * finish() must not wait forever for a recorder the OS has already killed.
 *
 * It awaited the MediaRecorder's stop event unbounded. A recorder iOS had
 * silently stopped never fired it, so the screen sat in a button-less
 * 'finishing' state with the audio safe in IndexedDB and no way to sync it.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../frontend/src/recorder/api', async () => {
	const actual = await vi.importActual<Record<string, unknown>>('../../frontend/src/recorder/api')
	return {
		...actual,
		recorderApi: {
			start: vi.fn().mockResolvedValue({ recording_id: 'rec-1' }),
			heartbeat: vi.fn().mockResolvedValue({ ok: true }),
			complete: () => new Promise(() => undefined),
		},
	}
})
vi.mock('../../frontend/src/recorder/idb', () => ({
	idb: {
		putRecording: vi.fn().mockResolvedValue(undefined),
		putChunk: vi.fn().mockResolvedValue(undefined),
		chunksFor: vi.fn().mockResolvedValue([]),
		getRecordings: vi.fn().mockResolvedValue([{ recordingId: 'rec-1' }]),
		countFor: vi.fn().mockResolvedValue(0),
	},
}))
const clientLog = vi.fn()
vi.mock('../../frontend/src/recorder/logger', () => ({
	clientLog: (...a: unknown[]) => clientLog(...a),
	ship: vi.fn().mockResolvedValue(undefined),
}))
vi.mock('../../frontend/src/recorder/sha', () => ({ sha256Hex: vi.fn(), sha256Blob: vi.fn() }))
vi.mock('../../frontend/src/recorder/transfer', () => ({ transferChunk: vi.fn() }))
vi.mock('../../frontend/src/recorder/useWakeLock', () => ({ wakeLockHeld: { value: true } }))

const { RecorderEngine } = await import('../../frontend/src/recorder/engine')

const track = { stop: vi.fn(), onended: null, onmute: null, onunmute: null, muted: false }

beforeEach(() => {
	vi.useFakeTimers()
	clientLog.mockClear()
	Object.defineProperty(navigator, 'mediaDevices', {
		value: {
			getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [track], getAudioTracks: () => [track] }),
		},
		configurable: true,
	})
	Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
	class WedgedMediaRecorder {
		static isTypeSupported = () => true
		state = 'recording'
		ondataavailable: unknown = null
		onerror: unknown = null
		onstop: unknown = null
		start = vi.fn()
		// stop() is accepted and nothing ever follows — no dataavailable, no stop
		stop = vi.fn()
		requestData = vi.fn()
	}
	vi.stubGlobal('MediaRecorder', WedgedMediaRecorder)
})

afterEach(() => {
	vi.useRealTimers()
	vi.unstubAllGlobals()
})

describe('finish() on a wedged recorder', () => {
	it('gives up waiting after five seconds and carries on with the sync', async () => {
		const engine = new RecorderEngine()
		await engine.start('token', 'round-1', 'assembly-1', 1)

		let finished = false
		const finishing = engine.finish().then(() => {
			finished = true
		})
		await vi.advanceTimersByTimeAsync(4_000)
		expect(finished).toBe(false)

		await vi.advanceTimersByTimeAsync(1_100)
		await finishing

		expect(finished).toBe(true)
		expect(track.stop).toHaveBeenCalled()
		expect(clientLog).toHaveBeenCalledWith('warn', 'recorder_stop_timeout', expect.anything())
		expect(engine.state.phase).not.toBe('finishing')
	})
})
