// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Leaving the recording screen must actually stop the recording.
 *
 * RecordingScreen unmounting used to tear down only its own timers, never the
 * engine — so a purge arriving mid-round (or any exit) left the MediaRecorder,
 * the mic tracks and the engine's heartbeat/storage intervals running with
 * nothing owning them. engine.stop() abandons live capture cleanly.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../frontend/src/recorder/api', async () => {
	const actual = await vi.importActual<Record<string, unknown>>('../../frontend/src/recorder/api')
	return { ...actual, recorderApi: { start: vi.fn().mockResolvedValue({ recording_id: 'rec-1' }) } }
})
vi.mock('../../frontend/src/recorder/idb', () => ({
	idb: {
		putRecording: vi.fn().mockResolvedValue(undefined),
		chunksFor: vi.fn().mockResolvedValue([]),
		getRecordings: vi.fn().mockResolvedValue([]),
		countFor: vi.fn().mockResolvedValue(0),
	},
}))
vi.mock('../../frontend/src/recorder/logger', () => ({ clientLog: vi.fn() }))
vi.mock('../../frontend/src/recorder/sha', () => ({ sha256Hex: vi.fn() }))

const { RecorderEngine } = await import('../../frontend/src/recorder/engine')

const track = { stop: vi.fn(), onended: null as unknown }
const recorderStop = vi.fn()

beforeEach(() => {
	vi.useFakeTimers()
	track.stop.mockReset()
	recorderStop.mockReset()
	Object.defineProperty(navigator, 'mediaDevices', {
		value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [track], getAudioTracks: () => [track] }) },
		configurable: true,
	})
	class FakeMediaRecorder {
		static isTypeSupported = () => true
		state = 'recording'
		ondataavailable: unknown = null
		onerror: unknown = null
		start = vi.fn()
		stop = () => {
			this.state = 'inactive'
			recorderStop()
		}
	}
	vi.stubGlobal('MediaRecorder', FakeMediaRecorder)
})

async function started() {
	const engine = new RecorderEngine()
	await engine.start('token', 'round-1', 'assembly-1', 1)
	return engine
}

describe('engine.stop()', () => {
	it('stops the microphone tracks and the recorder', async () => {
		const engine = await started()

		engine.stop()

		expect(recorderStop).toHaveBeenCalled()
		expect(track.stop).toHaveBeenCalled()
	})

	it('stops the heartbeat and storage timers', async () => {
		const engine = await started()
		const cleared: number[] = []
		const realClear = window.clearInterval.bind(window)
		vi.spyOn(window, 'clearInterval').mockImplementation((id) => {
			cleared.push(id as number)
			return realClear(id as number)
		})

		engine.stop()

		// startMonitors created two intervals; stop() must clear them
		expect(cleared.length).toBeGreaterThanOrEqual(2)
	})

	it('is idempotent and lets finish() no-op afterwards', async () => {
		const engine = await started()

		engine.stop()
		engine.stop()
		await engine.finish() // must not throw or re-open anything

		expect(recorderStop).toHaveBeenCalledTimes(1)
	})
})
