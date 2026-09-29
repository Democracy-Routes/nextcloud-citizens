// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The recorder must notice when the microphone goes quiet, and bridge it.
 *
 * A MediaRecorder can stop delivering audio with no error the page can catch:
 * iOS mutes the track while the screen is off, some phones freeze the tab.
 * The screen went on saying RECORDING with a climbing timer, the heartbeat
 * went on saying recording_active, and nothing was captured. Now a chunk that
 * is late while the page is on screen triggers a probe; silence to the probe
 * closes the MediaRecorder session and asks for the microphone back every
 * few seconds — into the SAME recording, as a new segment the server joins.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const heartbeat = vi.fn().mockResolvedValue({ ok: true })
vi.mock('../../frontend/src/recorder/api', async () => {
	const actual = await vi.importActual<Record<string, unknown>>('../../frontend/src/recorder/api')
	return {
		...actual,
		recorderApi: {
			start: vi.fn().mockResolvedValue({ recording_id: 'rec-1' }),
			heartbeat: (...a: unknown[]) => heartbeat(...a),
			complete: () => new Promise(() => undefined),
			recordingStatus: vi.fn(),
		},
	}
})
const stored: Array<{ seq: number; segment?: number; acked: boolean }> = []
vi.mock('../../frontend/src/recorder/idb', () => ({
	idb: {
		putRecording: vi.fn().mockResolvedValue(undefined),
		putChunk: vi.fn(async (chunk: { seq: number; segment?: number; acked: boolean }) => {
			const index = stored.findIndex((c) => c.seq === chunk.seq)
			if (index >= 0) stored[index] = chunk
			else stored.push(chunk)
		}),
		chunksFor: vi.fn(async () => stored.slice()),
		getRecordings: vi.fn(async () => [{ recordingId: 'rec-1', assemblyId: 'a1', roundId: 'r1' }]),
		countFor: vi.fn().mockResolvedValue(0),
	},
}))
const clientLog = vi.fn()
vi.mock('../../frontend/src/recorder/logger', () => ({
	clientLog: (...a: unknown[]) => clientLog(...a),
	ship: vi.fn().mockResolvedValue(undefined),
}))
vi.mock('../../frontend/src/recorder/sha', () => ({
	sha256Hex: vi.fn().mockResolvedValue('h'),
	sha256Blob: vi.fn().mockResolvedValue('h'),
}))
vi.mock('../../frontend/src/recorder/transfer', () => ({
	transferChunk: vi.fn().mockResolvedValue(undefined),
}))
vi.mock('../../frontend/src/recorder/useWakeLock', () => ({ wakeLockHeld: { value: true } }))

const { RecorderEngine, CHUNK_INTERVAL_MS } = await import('../../frontend/src/recorder/engine')

class FakeTrack {
	stop = vi.fn()
	onended: (() => void) | null = null
	onmute: (() => void) | null = null
	onunmute: (() => void) | null = null
	muted = false
	readyState = 'live'
}

class FakeMediaRecorder {
	static isTypeSupported = () => true
	static instances: FakeMediaRecorder[] = []
	/** what a probe finds in the buffer: audio (healthy) or nothing (dead) */
	static probeAnswersWithAudio = true
	state = 'inactive'
	ondataavailable: ((event: { data: Blob }) => void) | null = null
	onerror: (() => void) | null = null
	onstop: (() => void) | null = null
	start = vi.fn(() => {
		this.state = 'recording'
	})
	stop = vi.fn(() => {
		this.state = 'inactive'
		this.onstop?.()
	})
	requestData = vi.fn(() => {
		if (this.state !== 'recording') throw new Error('InvalidStateError')
		this.emit(FakeMediaRecorder.probeAnswersWithAudio ? new Blob(['audio']) : new Blob([]))
	})
	constructor() {
		FakeMediaRecorder.instances.push(this)
	}
	emit(blob: Blob): void {
		this.ondataavailable?.({ data: blob })
	}
}

const getUserMedia = vi.fn()
let tracks: FakeTrack[] = []

function newStream() {
	const track = new FakeTrack()
	tracks.push(track)
	return { getTracks: () => [track], getAudioTracks: () => [track] }
}

function setVisibility(state: 'visible' | 'hidden'): void {
	Object.defineProperty(document, 'visibilityState', { value: state, configurable: true })
	document.dispatchEvent(new Event('visibilitychange'))
}

const logged = (event: string) => clientLog.mock.calls.filter((call) => call[1] === event)

beforeEach(() => {
	vi.useFakeTimers()
	stored.length = 0
	tracks = []
	FakeMediaRecorder.instances = []
	FakeMediaRecorder.probeAnswersWithAudio = true
	clientLog.mockClear()
	heartbeat.mockClear()
	getUserMedia.mockReset().mockImplementation(async () => newStream())
	Object.defineProperty(navigator, 'mediaDevices', { value: { getUserMedia }, configurable: true })
	Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
	vi.stubGlobal('MediaRecorder', FakeMediaRecorder)
})

// every engine listens on `document`; one left running would answer the next
// test's visibility events too
const engines: InstanceType<typeof RecorderEngine>[] = []

afterEach(() => {
	for (const engine of engines.splice(0)) engine.stop()
	vi.useRealTimers()
	vi.unstubAllGlobals()
})

async function started() {
	const engine = new RecorderEngine()
	engines.push(engine)
	await engine.start('token', 'round-1', 'assembly-1', 1)
	return engine
}

const recorder = () => FakeMediaRecorder.instances[FakeMediaRecorder.instances.length - 1]
const STALL_MS = 3 * CHUNK_INTERVAL_MS

describe('the capture watchdog', () => {
	it('bridges a recorder that went quiet: same recording, next segment', async () => {
		const engine = await started()
		FakeMediaRecorder.probeAnswersWithAudio = false
		const first = recorder()

		await vi.advanceTimersByTimeAsync(STALL_MS + CHUNK_INTERVAL_MS)
		expect(first.requestData).toHaveBeenCalled()
		// the probe's two seconds pass with nothing in the buffer
		await vi.advanceTimersByTimeAsync(2_000)

		expect(logged('capture_interrupted')).toHaveLength(1)
		expect(logged('capture_interrupted')[0][2]).toMatchObject({ cause: 'capture_stalled', segment: 0 })
		expect(first.stop).toHaveBeenCalled()
		expect(tracks[0].stop).toHaveBeenCalled()
		// the microphone was asked back at once, and came back
		expect(getUserMedia).toHaveBeenCalledTimes(2)
		expect(engine.state.captureInterrupted).toBe(false)
		expect(engine.state.segment).toBe(1)
		expect(engine.state.micLostCause).toBe('')
		expect(engine.state.micLost).toBe(false)
		expect(engine.state.interruptions).toHaveLength(1)
		expect(engine.state.interruptions[0].cause).toBe('capture_stalled')
		expect(FakeMediaRecorder.instances).toHaveLength(2)
		expect(recorder().start).toHaveBeenCalledWith(CHUNK_INTERVAL_MS)
		expect(logged('capture_resumed')[0][2]).toMatchObject({ segment: 1 })

		// chunks from the new session carry the new segment number
		recorder().emit(new Blob(['more']))
		await vi.advanceTimersByTimeAsync(0)
		expect(stored.at(-1)).toMatchObject({ segment: 1 })
	})

	it('leaves a healthy recorder alone when the probe finds audio', async () => {
		const engine = await started()
		await vi.advanceTimersByTimeAsync(STALL_MS + CHUNK_INTERVAL_MS)
		expect(recorder().requestData).toHaveBeenCalled()
		await vi.advanceTimersByTimeAsync(2_000)

		expect(logged('capture_interrupted')).toHaveLength(0)
		expect(engine.state.captureInterrupted).toBe(false)
		expect(engine.state.segment).toBe(0)
	})

	it('never probes while the page is hidden, however long the silence', async () => {
		await started()
		setVisibility('hidden')
		await vi.advanceTimersByTimeAsync(6 * CHUNK_INTERVAL_MS)

		expect(recorder().requestData).not.toHaveBeenCalled()
		expect(logged('capture_interrupted')).toHaveLength(0)
	})

	it('discards a probe the page hid during', async () => {
		await started()
		FakeMediaRecorder.probeAnswersWithAudio = false
		await vi.advanceTimersByTimeAsync(STALL_MS + CHUNK_INTERVAL_MS)
		expect(recorder().requestData).toHaveBeenCalled()

		setVisibility('hidden')
		await vi.advanceTimersByTimeAsync(2_000)

		expect(logged('capture_interrupted')).toHaveLength(0)
	})

	it('treats a recorder that refuses the probe as gone at once', async () => {
		const engine = await started()
		recorder().state = 'inactive' // the OS killed it without a word

		await vi.advanceTimersByTimeAsync(STALL_MS + CHUNK_INTERVAL_MS)

		expect(logged('capture_interrupted')[0][2]).toMatchObject({ probe: 'request_failed' })
		expect(engine.state.segment).toBe(1)
	})

	it('reports what happened while the page was hidden', async () => {
		await started()
		setVisibility('hidden')
		recorder().emit(new Blob(['a']))
		recorder().emit(new Blob(['b']))
		setVisibility('visible')

		const line = logged('capture_after_background')
		expect(line).toHaveLength(1)
		expect(line[0][2]).toMatchObject({ chunksWhileHidden: 2, interrupted: false })
	})

	describe('a muted track', () => {
		it('is the microphone gone if it stays muted on screen', async () => {
			const engine = await started()
			tracks[0].muted = true
			tracks[0].onmute?.()
			await vi.advanceTimersByTimeAsync(5_000)

			expect(logged('capture_interrupted')[0][2]).toMatchObject({ cause: 'track_muted' })
			expect(engine.state.segment).toBe(1)
		})

		it('is only a log line when it unmutes within the grace period', async () => {
			const engine = await started()
			tracks[0].muted = true
			tracks[0].onmute?.()
			await vi.advanceTimersByTimeAsync(2_000)
			tracks[0].muted = false
			tracks[0].onunmute?.()
			await vi.advanceTimersByTimeAsync(5_000)

			expect(logged('track_muted')).toHaveLength(1)
			expect(logged('track_unmuted')).toHaveLength(1)
			expect(logged('capture_interrupted')).toHaveLength(0)
			expect(engine.state.segment).toBe(0)
		})

		it('is not judged by a timer that ran across a hide and a show', async () => {
			// iOS: mutes on hide, unmutes on return — the grace timer set at the
			// mute fires the instant the page resumes, before the unmute lands
			const engine = await started()
			setVisibility('hidden')
			tracks[0].muted = true
			tracks[0].onmute?.()
			await vi.advanceTimersByTimeAsync(1_000)
			setVisibility('visible')
			await vi.advanceTimersByTimeAsync(4_500)
			tracks[0].muted = false
			tracks[0].onunmute?.()
			await vi.advanceTimersByTimeAsync(10_000)

			expect(engine.state.segment).toBe(0)
			expect(logged('capture_interrupted')).toHaveLength(0)
		})
	})

	it('keeps asking for the microphone until it comes back', async () => {
		const engine = await started()
		FakeMediaRecorder.probeAnswersWithAudio = false
		const refused = Object.assign(new Error('busy'), { name: 'NotReadableError' })
		getUserMedia
			.mockRejectedValueOnce(refused)
			.mockRejectedValueOnce(refused)
			.mockRejectedValueOnce(refused)

		await vi.advanceTimersByTimeAsync(STALL_MS + CHUNK_INTERVAL_MS + 2_000)
		expect(engine.state.captureInterrupted).toBe(true)
		expect(logged('capture_resume_failed')).toHaveLength(1)

		await vi.advanceTimersByTimeAsync(2 * 5_000)
		expect(logged('capture_resume_failed')).toHaveLength(3)
		expect(engine.state.captureInterrupted).toBe(true)

		await vi.advanceTimersByTimeAsync(5_000)
		expect(engine.state.captureInterrupted).toBe(false)
		expect(engine.state.segment).toBe(1)
		expect(logged('capture_resumed')[0][2]).toMatchObject({ attempts: 4 })
	})

	it('asks at once when the page comes back rather than waiting out the timer', async () => {
		const engine = await started()
		FakeMediaRecorder.probeAnswersWithAudio = false
		getUserMedia.mockRejectedValueOnce(new Error('busy'))
		await vi.advanceTimersByTimeAsync(STALL_MS + CHUNK_INTERVAL_MS + 2_000)
		expect(engine.state.captureInterrupted).toBe(true)
		const calls = getUserMedia.mock.calls.length

		setVisibility('hidden')
		setVisibility('visible')
		await vi.advanceTimersByTimeAsync(0)

		expect(getUserMedia.mock.calls.length).toBe(calls + 1)
		expect(engine.state.captureInterrupted).toBe(false)
	})

	it('gives up after ten minutes of refusals and finishes with what it has', async () => {
		const engine = await started()
		recorder().emit(new Blob(['a']))
		await vi.advanceTimersByTimeAsync(0)
		FakeMediaRecorder.probeAnswersWithAudio = false
		getUserMedia.mockRejectedValue(new Error('busy'))

		await vi.advanceTimersByTimeAsync(STALL_MS + CHUNK_INTERVAL_MS + 2_000)
		expect(engine.state.captureInterrupted).toBe(true)
		await vi.advanceTimersByTimeAsync(121 * 5_000)

		expect(engine.state.micLost).toBe(true)
		expect(engine.state.micLostCause).toBe('capture_stalled')
		expect(engine.state.captureInterrupted).toBe(false)
		expect(engine.state.phase).not.toBe('recording')
		expect(logged('microphone_lost')[0][2]).toMatchObject({ cause: 'capture_stalled' })
	})

	it('can be finished while the interruption is still being bridged', async () => {
		const engine = await started()
		recorder().emit(new Blob(['a']))
		await vi.advanceTimersByTimeAsync(0)
		FakeMediaRecorder.probeAnswersWithAudio = false
		getUserMedia.mockRejectedValue(new Error('busy'))
		await vi.advanceTimersByTimeAsync(STALL_MS + CHUNK_INTERVAL_MS + 2_000)
		expect(engine.state.captureInterrupted).toBe(true)

		await engine.finish()

		expect(engine.state.captureInterrupted).toBe(false)
		expect(engine.state.phase).toBe('syncing')
		// no further attempts on a finished recording
		const calls = getUserMedia.mock.calls.length
		await vi.advanceTimersByTimeAsync(30_000)
		expect(getUserMedia.mock.calls.length).toBe(calls)
	})

	it('tells the server whether audio is arriving, and whether the screen is held', async () => {
		const engine = await started()
		expect(heartbeat).toHaveBeenLastCalledWith(
			'token',
			expect.objectContaining({ capture_ok: true, screen_awake: true }),
		)

		FakeMediaRecorder.probeAnswersWithAudio = false
		getUserMedia.mockRejectedValue(new Error('busy'))
		await vi.advanceTimersByTimeAsync(STALL_MS + CHUNK_INTERVAL_MS + 2_000)
		expect(engine.state.captureInterrupted).toBe(true)
		heartbeat.mockClear()
		await vi.advanceTimersByTimeAsync(20_000)

		expect(heartbeat).toHaveBeenLastCalledWith(
			'token',
			expect.objectContaining({ recording_active: true, capture_ok: false }),
		)
	})

	it('stop() takes every listener and timer with it', async () => {
		const engine = await started()
		const removed = vi.spyOn(document, 'removeEventListener')

		engine.stop()

		expect(removed).toHaveBeenCalledWith('visibilitychange', expect.any(Function))
		expect(removed).toHaveBeenCalledWith('resume', expect.any(Function))
		expect(tracks[0].onmute).toBeNull()
		expect(tracks[0].onended).toBeNull()
		await vi.advanceTimersByTimeAsync(10 * CHUNK_INTERVAL_MS)
		expect(logged('capture_interrupted')).toHaveLength(0)
	})
})
