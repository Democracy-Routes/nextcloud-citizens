// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The recorder must not claim the server validated audio it never confirmed.
 *
 * After five minutes of polling without the server reaching AUDIO_READY, the
 * engine declared 'done' and marked the recording server-complete. The screen
 * then told the table "uploaded and validated by the server" and offered to
 * clear the phone's copy — which, if the server really had not finished, was
 * the only remaining one.
 *
 * The honest outcome is a separate phase: uploaded, not confirmed.
 */
import { describe, expect, it, vi } from 'vitest'

const recordingStatus = vi.fn()

vi.mock('../../frontend/src/recorder/api', () => ({
	recorderApi: {
		recordingStatus: (...args: unknown[]) => recordingStatus(...args),
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
// a real stored recording, so markServerComplete has something to mark — with
// an empty list the assertion below would pass no matter what the code does
const storedRecording = { recordingId: 'rec-1', serverComplete: false }
vi.mock('../../frontend/src/recorder/idb', () => ({
	idb: {
		getRecordings: vi.fn(async () => [storedRecording]),
		putRecording: (...args: unknown[]) => putRecording(...args),
	},
}))

vi.mock('../../frontend/src/recorder/logger', () => ({ clientLog: vi.fn() }))
vi.mock('../../frontend/src/recorder/sha', () => ({ sha256Hex: vi.fn() }))

const { RecorderEngine } = await import('../../frontend/src/recorder/engine')

/** Drive the private poll loop with timers collapsed. */
async function runPollLoop(engine: InstanceType<typeof RecorderEngine>) {
	vi.useFakeTimers()
	const promise = (engine as unknown as {
		pollUntilProcessed: () => Promise<void>
	}).pollUntilProcessed()
	await vi.runAllTimersAsync()
	await promise
	vi.useRealTimers()
}

describe('when the server never confirms the assembled audio', () => {
	it('reports it as uploaded, not done', async () => {
		recordingStatus.mockResolvedValue({ state: 'ASSEMBLING', error_code: '' })
		const engine = new RecorderEngine()
		engine.state.recordingId = 'rec-1'

		await runPollLoop(engine)

		expect(engine.state.phase).toBe('uploaded')
	})

	it('does not mark the recording server-complete', async () => {
		recordingStatus.mockResolvedValue({ state: 'ASSEMBLING', error_code: '' })
		putRecording.mockClear()
		storedRecording.serverComplete = false
		const engine = new RecorderEngine()
		engine.state.recordingId = 'rec-1'

		await runPollLoop(engine)

		// serverComplete is what lets the phone delete its own copy — the last
		// one, if the server really has not finished
		expect(putRecording).not.toHaveBeenCalled()
		expect(storedRecording.serverComplete).toBe(false)
	})

	it('still reports done when the server does confirm', async () => {
		recordingStatus.mockResolvedValue({ state: 'AUDIO_READY', error_code: '' })
		const engine = new RecorderEngine()
		engine.state.recordingId = 'rec-1'

		await runPollLoop(engine)

		expect(engine.state.phase).toBe('done')
	})

	it('a later check can still promote uploaded to done', async () => {
		recordingStatus.mockResolvedValue({ state: 'ASSEMBLING', error_code: '' })
		const engine = new RecorderEngine()
		engine.state.recordingId = 'rec-1'
		await runPollLoop(engine)
		expect(engine.state.phase).toBe('uploaded')

		recordingStatus.mockResolvedValue({ state: 'TRANSCRIBED', error_code: '' })
		await engine.recheckServerState()

		expect(engine.state.phase).toBe('done')
	})
})
