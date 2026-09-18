// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * A reload during "Synchronizing" must not brick the recording.
 *
 * On recovery the engine re-posts /complete, and the server 409s once the
 * recording is ASSEMBLING or beyond — exactly where a reload in that window
 * lands. That 409 is not a failure: the server HAS the recording. It is only
 * verifiable once the manifest exists at AUDIO_READY, so the phone polls
 * until then — or settles as failed on AUDIO_INVALID or a prefix salvage,
 * both of which re-polling cannot change.
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
const storedRecording = { recordingId: 'rec-1', serverComplete: false, totalChunks: 3 }
// The phone captured three chunks; the engine's declared total matches. Each
// test decides how many of them the server ended up with.
let storedChunks = [
	{ seq: 0, sizeBytes: 5, sha256: 'chunk0' },
	{ seq: 1, sizeBytes: 5, sha256: 'chunk1' },
	{ seq: 2, sizeBytes: 5, sha256: 'chunk2' },
]
vi.mock('../../frontend/src/recorder/idb', () => ({
	idb: {
		getRecordings: vi.fn(async () => [storedRecording]),
		putRecording: (...a: unknown[]) => putRecording(...a),
		chunksFor: vi.fn(async () => storedChunks),
	},
}))
vi.mock('../../frontend/src/recorder/logger', () => ({ clientLog: vi.fn() }))
vi.mock('../../frontend/src/recorder/sha', () => ({ sha256Hex: vi.fn(async () => 'manifest') }))

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
		recordingStatus.mockResolvedValue({ state: 'AUDIO_READY', error_code: '', total_chunks: 3,
			audio_available: true, audio_manifest_sha256: 'manifest', audio_manifest_bytes: 15 })
		const engine = newEngine()

		await runComplete(engine)

		expect(engine.state.phase).toBe('done')
		expect(storedRecording.serverComplete).toBe(true)
	})

	it('retains the local copy when the server only salvaged a prefix', async () => {
		complete.mockRejectedValue(new RecorderApiError(409, 'Recording is AUDIO_READY'))
		recordingStatus.mockResolvedValue({ state: 'AUDIO_READY', total_chunks: 1,
			audio_available: true, audio_manifest_sha256: 'different', audio_manifest_bytes: 2 })
		const engine = newEngine()
		await runComplete(engine)
		expect(engine.state.phase).toBe('failed')
		expect(storedRecording.serverComplete).toBe(false)
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

	it('survives ASSEMBLING: keeps polling until the manifest can be verified', async () => {
		// The wedge case. A manifest only exists once the recording is
		// AUDIO_READY, so every status poll WHILE assembling fails verification.
		// Failing there stranded the phone on a dead-end screen whose Try-again
		// re-posted the same deterministic 409 — the local copy was never
		// purge-safe and the recovery screen came back on every boot.
		complete.mockRejectedValue(new RecorderApiError(409, 'Recording is ASSEMBLING'))
		let polls = 0
		recordingStatus.mockImplementation(async () => {
			polls += 1
			if (polls < 3) {
				return { state: 'ASSEMBLING', error_code: '', total_chunks: null,
					audio_available: false }
			}
			return { state: 'AUDIO_READY', error_code: '', total_chunks: 3,
				audio_available: true, audio_manifest_sha256: 'manifest', audio_manifest_bytes: 15 }
		})
		const engine = newEngine()

		await runComplete(engine)

		expect(engine.state.phase).toBe('done')
		expect(storedRecording.serverComplete).toBe(true)
		expect(polls).toBeGreaterThanOrEqual(3)
	})

	it('settles as failed when the manifest disagrees at EQUAL length', async () => {
		// The gap the first loop left open: it exited only when the server had
		// FEWER chunks. Same count, different hash or byte total, also cannot
		// change by re-asking — it re-polled every three seconds forever.
		complete.mockRejectedValue(new RecorderApiError(409, 'Recording is AUDIO_READY'))
		recordingStatus.mockResolvedValue({ state: 'AUDIO_READY', error_code: '', total_chunks: 3,
			audio_available: true, audio_manifest_sha256: 'different', audio_manifest_bytes: 15 })
		const engine = newEngine()

		await runComplete(engine)

		expect(engine.state.phase).toBe('failed')
		expect(engine.state.errorKind).toBe('rejected')
		expect(storedRecording.serverComplete).toBe(false)
	})

	it('stops polling when the session is revoked mid-wait, keeping the audio', async () => {
		// a gone session cannot be polled back into existence; the old loop
		// retried the 401 at a flat three seconds with no deadline
		complete.mockRejectedValue(new RecorderApiError(409, 'Recording is ASSEMBLING'))
		let polls = 0
		recordingStatus.mockImplementation(async () => {
			polls += 1
			if (polls < 2) return { state: 'ASSEMBLING', error_code: '', total_chunks: null }
			throw new RecorderApiError(401, 'Session revoked')
		})
		const engine = newEngine()

		await runComplete(engine)

		expect(engine.state.phase).toBe('failed')
		expect(engine.state.errorKind).toBe('gone')
		expect(storedRecording.serverComplete).toBe(false)
	})

	it('a recording that assembles INVALID settles as failed, not as an endless poll', async () => {
		complete.mockRejectedValue(new RecorderApiError(409, 'Recording is ASSEMBLING'))
		let polls = 0
		recordingStatus.mockImplementation(async () => {
			polls += 1
			if (polls < 2) return { state: 'ASSEMBLING', error_code: '', total_chunks: null }
			return { state: 'AUDIO_INVALID', error_code: 'CHUNKS_GONE', total_chunks: 1 }
		})
		const engine = newEngine()

		await runComplete(engine)

		expect(engine.state.phase).toBe('failed')
		expect(engine.state.error).toContain('CHUNKS_GONE')
		expect(storedRecording.serverComplete).toBe(false)
	})
})
