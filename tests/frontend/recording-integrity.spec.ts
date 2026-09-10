// SPDX-License-Identifier: AGPL-3.0-or-later
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { RecorderEngine } from '../../frontend/src/recorder/engine'
import { idb, type StoredRecording, type StoredChunk } from '../../frontend/src/recorder/idb'
import { recorderApi, RecorderApiError } from '../../frontend/src/recorder/api'
import { sha256Hex } from '../../frontend/src/recorder/sha'

vi.mock('../../frontend/src/recorder/logger', () => ({ clientLog: vi.fn() }))

let meta: StoredRecording
let chunks: StoredChunk[]
beforeEach(async () => {
	meta = { recordingId: 'rec', assemblyId: 'a1', roundId: 'round', tableNumber: 1,
		mimeType: 'audio/webm', startedAt: 1, finishedAt: 2, totalChunks: 1, serverComplete: false }
	chunks = [{ key: 'rec:0', recordingId: 'rec', seq: 0, sizeBytes: 5, blob: new Blob(['audio']),
		sha256: await sha256Hex(new TextEncoder().encode('audio').buffer), acked: true, createdAt: 1, attempts: 1 }]
	vi.spyOn(idb, 'getRecordings').mockImplementation(async () => [meta])
	vi.spyOn(idb, 'putRecording').mockResolvedValue('rec')
	vi.spyOn(idb, 'chunksFor').mockImplementation(async () => chunks)
	vi.spyOn(recorderApi, 'heartbeat').mockResolvedValue({} as never)
})
afterEach(() => vi.restoreAllMocks())

async function proof() {
	return { state: 'AUDIO_READY', total_chunks: 1, audio_available: true, audio_manifest_bytes: 5,
		audio_manifest_sha256: await sha256Hex(new TextEncoder().encode(`0:5:${chunks[0].sha256}\n`).buffer) }
}
it('matches the real ordered manifest before allowing cleanup', async () => {
	vi.spyOn(recorderApi, 'recordingStatus').mockResolvedValue(await proof() as never)
	const engine = new RecorderEngine()
	engine.state.recordingId = 'rec'
	await engine.recheckServerState()
	expect(engine.state.phase).toBe('done')
	expect(meta.serverComplete).toBe(true)
	expect(meta.verificationVersion).toBe(1)
})

it.each(['hash', 'size', 'count', 'deleted', 'local_gap', 'capture_incomplete', 'legacy'])('keeps local audio on %s', async (failure) => {
	const status = await proof()
	if (failure === 'hash') status.audio_manifest_sha256 = 'wrong'
	if (failure === 'size') status.audio_manifest_bytes = 4
	if (failure === 'count') status.total_chunks = 2
	if (failure === 'deleted') status.audio_available = false
	if (failure === 'local_gap') chunks[0].seq = 1
	if (failure === 'capture_incomplete') meta.captureIncomplete = true
	if (failure === 'legacy') status.audio_manifest_sha256 = ''
	vi.spyOn(recorderApi, 'recordingStatus').mockResolvedValue(status as never)
	const engine = new RecorderEngine()
	engine.state.recordingId = 'rec'
	await engine.recheckServerState()
	expect(engine.state.phase).toBe('failed')
	expect(meta.serverComplete).toBe(false)
})

it('retains a failed local write in memory and retries the full capture without truncation', async () => {
	chunks = []
	meta.totalChunks = null
	vi.spyOn(idb, 'putChunk').mockRejectedValueOnce(new Error('quota full')).mockImplementation(async (chunk) => {
		chunks.push(chunk)
		return chunk.key
	})
	vi.spyOn(recorderApi, 'uploadChunk').mockRejectedValue(new RecorderApiError(401, 'expired'))
	const engine = new RecorderEngine()
	engine.state.recordingId = 'rec'
	engine.state.phase = 'recording'
	const internal = engine as unknown as { enqueueChunk(blob: Blob): void; chunkPipeline: Promise<void>;
		mediaRecorder: { onstop: (() => void) | null; stop(): void } }
	internal.enqueueChunk(new Blob(['irreplaceable audio']))
	await internal.chunkPipeline
	expect(engine.state.storageError).toBe(true)
	expect(await (await engine.localAudio()).text()).toBe('irreplaceable audio')
	internal.mediaRecorder = { onstop: null, stop() { this.onstop?.() } }
	await engine.finish()
	expect(meta.totalChunks).toBe(1)
	expect(meta.captureIncomplete).toBe(true)
	expect(engine.state.phase).toBe('failed')
	await engine.retrySync()
	engine.stop()
	expect(chunks).toHaveLength(1)
	expect(meta.totalChunks).toBe(1)
	expect(meta.captureIncomplete).toBe(false)
	expect(engine.state.storageError).toBe(false)
	expect(await chunks[0].blob.text()).toBe('irreplaceable audio')
})

it.each([401, 413, 422])('upload rejection %i does not stop active capture or retry forever', async (status) => {
	chunks[0].acked = false
	const upload = vi.spyOn(recorderApi, 'uploadChunk').mockRejectedValue(new RecorderApiError(status, 'rejected'))
	vi.spyOn(recorderApi, 'partStatus').mockRejectedValue(new RecorderApiError(status, 'rejected'))
	const engine = new RecorderEngine()
	engine.state.recordingId = 'rec'
	engine.state.phase = 'recording'
	const run = engine as unknown as { runUploader(): Promise<void> }
	await run.runUploader()
	await run.runUploader()
	expect(upload).toHaveBeenCalledTimes(1)
	expect(engine.state.phase).toBe('recording')
	expect(engine.state.uploadOnline).toBe(false)
	expect(chunks[0].acked).toBe(false)
})
