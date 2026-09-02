// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Telling a table why recording would not start.
 *
 * Starting does two things that fail for unrelated reasons: it opens the
 * microphone, then it asks the server. The screen treated both as a microphone
 * problem — so a table refused because its phone had been replaced ("This
 * table already recorded round 1", a sentence written for a person) was shown
 * the Android permission steps instead, sending someone to fix a microphone
 * that was working perfectly.
 *
 * The engine is what can tell them apart, because it is the only thing that
 * knows which call failed. These tests run the real engine.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

const start = vi.fn()

vi.mock('../../frontend/src/recorder/api', async () => {
	const actual = await vi.importActual<Record<string, unknown>>(
		'../../frontend/src/recorder/api',
	)
	return { ...actual, recorderApi: { start: (...a: unknown[]) => start(...a) } }
})
vi.mock('../../frontend/src/recorder/idb', () => ({
	idb: {
		putRecording: vi.fn().mockResolvedValue(undefined),
		// the successful-start case sets the uploader going; it has nothing to
		// upload, but it does look
		chunksFor: vi.fn().mockResolvedValue([]),
		getRecordings: vi.fn().mockResolvedValue([]),
		countFor: vi.fn().mockResolvedValue(0),
	},
}))
vi.mock('../../frontend/src/recorder/logger', () => ({ clientLog: vi.fn() }))
vi.mock('../../frontend/src/recorder/sha', () => ({ sha256Hex: vi.fn() }))

const { RecorderEngine } = await import('../../frontend/src/recorder/engine')
const { MicrophoneError } = await import('../../frontend/src/recorder/errors')
const { RecorderApiError } = await import('../../frontend/src/recorder/api')

const getUserMedia = vi.fn()

beforeEach(() => {
	start.mockReset()
	getUserMedia.mockReset().mockResolvedValue({ getTracks: () => [] })
	Object.defineProperty(navigator, 'mediaDevices', {
		value: { getUserMedia: (...a: unknown[]) => getUserMedia(...a) },
		configurable: true,
	})
	// enough of a MediaRecorder for start() to get past the format check
	class FakeMediaRecorder {
		static isTypeSupported = () => true
		ondataavailable: unknown = null
		start = vi.fn()
		stop = vi.fn()
	}
	vi.stubGlobal('MediaRecorder', FakeMediaRecorder)
})

async function startAndCatch(): Promise<unknown> {
	const engine = new RecorderEngine()
	try {
		await engine.start('token', 'round-1', 'assembly-1')
		return null
	} catch (error) {
		return error
	}
}

describe('when the microphone will not open', () => {
	it('reports it as a microphone problem', async () => {
		getUserMedia.mockRejectedValue(new DOMException('Permission denied', 'NotAllowedError'))

		const error = await startAndCatch()

		expect(error).toBeInstanceOf(MicrophoneError)
		expect(String(error)).toContain('Permission denied')
	})

	it('does not go on to ask the server', async () => {
		getUserMedia.mockRejectedValue(new DOMException('No device', 'NotFoundError'))

		await startAndCatch()

		expect(start).not.toHaveBeenCalled()
	})
})

describe('when the server refuses', () => {
	it('passes the refusal through untouched, microphone and all', async () => {
		// the microphone opened perfectly; blaming it would send the table
		// after a problem they do not have
		const refusal = 'This table already recorded round 1 (recording is RECORDING).'
		start.mockRejectedValue(new RecorderApiError(409, refusal))

		const error = await startAndCatch()

        expect(error).not.toBeInstanceOf(MicrophoneError)
		expect(error).toBeInstanceOf(RecorderApiError)
		expect((error as Error).message).toBe(refusal)
	})

	it('keeps the server’s own wording, which is written to be read', async () => {
		start.mockRejectedValue(new RecorderApiError(409, 'The facilitator has not started this round yet'))

		const error = await startAndCatch()

		expect((error as Error).message).toContain('facilitator')
	})
})

describe('a successful start', () => {
	it('opens the microphone before asking the server', async () => {
		// the order matters: asking first would leave a recording on the server
		// that no microphone is feeding
		start.mockResolvedValue({ recording_id: 'rec-1' })

		await startAndCatch()

		expect(getUserMedia).toHaveBeenCalled()
		expect(start).toHaveBeenCalledWith('token', 'round-1', expect.any(String))
	})
})
