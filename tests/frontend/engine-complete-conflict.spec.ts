// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * A reload during "Synchronizing" must not brick the recording.
 *
 * On recovery the engine re-posts /complete, and the server 409s once the
 * recording is ASSEMBLING or beyond — exactly where a reload in that window
 * lands. Treating that 409 as a failure told the table its sync had failed for
 * a recording the server had already finished, never set serverComplete, and
 * so re-entered the recovery screen on every boot forever, with the purge
 * blocked behind it.
 */
import { describe, expect, it, vi } from 'vitest'

const recordingStatus = vi.fn()
const complete = vi.fn()

vi.mock('../../frontend/src/recorder/api', () => ({
	recorderApi: {
		recordingStatus: (...a: unknown[]) => recordingStatus(...a),
		complete: (...a: unknown[]) => complete(...a),
	},
	RecorderApiError: class extends Error {
		status: number
		constructor(status: number, message: string) {
			super(message)
			this.status = status
		}
	},
}))

const putRecording = vi.fn().mockResolvedValue(undefined)
const storedRecording = { recordingId: 'rec-1', serverComplete: false }
vi.mock('../../frontend/src/recorder/idb', () => ({
	idb: {
		getRecordings: vi.fn(async () => [storedRecording]),
		putRecording: (...a: unknown[]) => putRecording(...a),
		chunksFor: vi.fn(async () => []),
	},
}))
vi.mock('../../frontend/src/recorder/logger', () => ({ clientLog: vi.fn() }))
vi.mock('../../frontend/src/recorder/sha', () => ({ sha256Hex: vi.fn() }))

const { RecorderEngine } = await import('../../frontend/src/recorder/engine')
const { RecorderApiError } = await import('../../frontend/src/recorder/api')

async function runComplete(engine: InstanceType<typeof RecorderEngine>) {
	vi.useFakeTimers()
	const promise = (engine as unknown as { sendComplete: () => Promise<void> }).sendComplete()
	await vi.runAllTimersAsync()
	await promise
	vi.useRealTimers()
}

describe('a /complete that 409s because the recording is already finished', () => {
	function newEngine() {
		const engine = new RecorderEngine()
		engine.state.recordingId = 'rec-1'
		;(engine as unknown as { totalChunks: number }).totalChunks = 3
		storedRecording.serverComplete = false
		putRecording.mockClear()
		return engine
	}

	it('recognises the recording as done and marks it complete', async () => {
		complete.mockRejectedValue(new RecorderApiError(409, 'Recording is ASSEMBLING'))
		recordingStatus.mockResolvedValue({ state: 'AUDIO_READY', error_code: '' })
		const engine = newEngine()

		await runComplete(engine)

		expect(engine.state.phase).toBe('done')
		expect(storedRecording.serverComplete).toBe(true)
	})

	it('still fails on a 409 for a recording the server has NOT finished', async () => {
		// a genuine conflict (wrong state, not a finished one) must not be
		// swallowed as success
		complete.mockRejectedValue(new RecorderApiError(409, 'Recording is CREATED'))
		recordingStatus.mockResolvedValue({ state: 'CREATED', error_code: '' })
		const engine = newEngine()

		await runComplete(engine)

		expect(engine.state.phase).toBe('failed')
		expect(storedRecording.serverComplete).toBe(false)
	})
})
