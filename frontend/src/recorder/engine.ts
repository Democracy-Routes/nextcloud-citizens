// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/*
 * Recording engine: one MediaRecorder session, periodic chunks written to
 * IndexedDB FIRST, then uploaded asynchronously with acknowledgment tracking,
 * exponential-backoff retry, heartbeats and crash recovery.
 * The network is never required to preserve audio (brief §17–§20).
 */

import { reactive } from 'vue'
import { RecorderApiError, recorderApi } from './api'
import { isGoneError, isTransientError } from './errors'
import { idb, type StoredRecording } from './idb'
import { clientLog } from './logger'
import { sha256Hex } from './sha'

// ~10 s chunks by default (brief §17.2); overridable via ?chunkms= for tests
export const CHUNK_INTERVAL_MS = (() => {
	const override = Number(new URLSearchParams(window.location.search).get('chunkms'))
	return Number.isFinite(override) && override >= 250 ? override : 10_000
})()
const RETRY_BASE_MS = 3_000
const RETRY_MAX_MS = 60_000
const HEARTBEAT_MS = 20_000
const STORAGE_CHECK_MS = 60_000
const LOW_STORAGE_MB = 100

const MIME_CANDIDATES = [
	'audio/webm;codecs=opus',
	'audio/webm',
	'audio/ogg;codecs=opus',
	'audio/mp4',
]

export function pickMimeType(): string | null {
	if (typeof MediaRecorder === 'undefined') return null
	for (const candidate of MIME_CANDIDATES) {
		if (MediaRecorder.isTypeSupported(candidate)) return candidate
	}
	return null
}

export interface EngineState {
	/** 'done' means the SERVER confirmed the audio; 'uploaded' means every
	 * chunk was accepted but the server never got round to confirming within
	 * the poll window. The difference decides whether this phone may offer to
	 * delete its own copy, so the two must never be conflated. */
	phase: 'idle' | 'recording' | 'finishing' | 'syncing' | 'done' | 'uploaded' | 'failed'
	recordingId: string
	startedAt: number
	localChunks: number
	ackedChunks: number
	storageError: boolean
	lowStorage: boolean
	uploadOnline: boolean
	/** why the last upload failed, so the table is told the truth */
	uploadFailure: '' | 'network' | 'server'
	retryInMs: number
	serverState: string
	error: string
	/** 'gone' = the server definitively no longer knows this recording/session
	 * (deleted assembly, reset instance) — retrying can never succeed */
	errorKind: '' | 'gone' | 'transient'
}


export class RecorderEngine {
	state: EngineState = reactive({
		phase: 'idle',
		recordingId: '',
		startedAt: 0,
		localChunks: 0,
		ackedChunks: 0,
		storageError: false,
		lowStorage: false,
		uploadOnline: true,
		uploadFailure: '',
		retryInMs: 0,
		serverState: '',
		error: '',
		errorKind: '',
	})

	private token = ''
	/** so the heartbeat can report how much of THIS assembly is still here */
	private assemblyId = ''
	private stream: MediaStream | null = null
	private mediaRecorder: MediaRecorder | null = null
	private seq = 0
	private totalChunks: number | null = null
	// serializes async chunk persistence so sequence order matches event order
	private chunkPipeline: Promise<void> = Promise.resolve()
	private uploaderActive = false
	private stopRequested = false
	private retryDelay = RETRY_BASE_MS
	private wakeUploader: (() => void) | null = null
	private heartbeatTimer = 0
	private storageTimer = 0
	private onlineListener = () => {
		clientLog('info', 'network_online')
		this.retryDelay = RETRY_BASE_MS
		this.kickUploader()
	}

	async start(token: string, roundId: string, assemblyId: string): Promise<void> {
		this.assemblyId = assemblyId
		this.token = token
		const mimeType = pickMimeType()
		if (!mimeType) throw new Error('This browser cannot record audio (no supported format)')

		this.stream = await navigator.mediaDevices.getUserMedia({
			audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: true },
		})
		const started = await recorderApi.start(token, roundId, mimeType)
		this.state.recordingId = started.recording_id
		this.state.startedAt = Date.now()
		this.state.phase = 'recording'
		clientLog('info', 'recording_started', { recordingId: started.recording_id, mimeType })

		await idb.putRecording({
			recordingId: started.recording_id,
			assemblyId,
			roundId,
			tableNumber: 0,
			mimeType,
			startedAt: this.state.startedAt,
			finishedAt: null,
			totalChunks: null,
			serverComplete: false,
		})

		this.mediaRecorder = new MediaRecorder(this.stream, { mimeType })
		this.mediaRecorder.ondataavailable = (event: BlobEvent) => {
			if (event.data && event.data.size > 0) this.enqueueChunk(event.data)
		}
		this.mediaRecorder.start(CHUNK_INTERVAL_MS)
		this.startMonitors()
		this.runUploader()
	}

	/** Resume synchronization of a recording found in IndexedDB after a
	 * reload/crash. The microphone session is gone (a reload always stops
	 * recording); every persisted chunk is recoverable (brief §20). */
	async resumeSync(token: string, recordingMeta: StoredRecording): Promise<void> {
		// plain copy: the caller may hand us a Vue reactive proxy, which
		// IndexedDB's structured clone cannot serialize
		const recording: StoredRecording = { ...recordingMeta }
		this.token = token
		this.state.recordingId = recording.recordingId
		this.state.startedAt = recording.startedAt
		const chunks = await idb.chunksFor(recording.recordingId)
		this.seq = chunks.length === 0 ? 0 : Math.max(...chunks.map((c) => c.seq)) + 1
		this.totalChunks = recording.totalChunks ?? this.seq
		this.state.localChunks = chunks.length
		this.state.ackedChunks = chunks.filter((c) => c.acked).length
		this.state.phase = 'syncing'
		clientLog('info', 'recovery_resume', {
			recordingId: recording.recordingId,
			chunks: chunks.length,
			pending: chunks.length - this.state.ackedChunks,
		})
		if (recording.totalChunks === null) {
			recording.totalChunks = this.totalChunks
			recording.finishedAt = recording.finishedAt ?? Date.now()
			await idb.putRecording(recording)
		}
		this.startMonitors()
		this.runUploader()
	}

	get mediaStream(): MediaStream | null {
		return this.stream
	}

	retryNow(): void {
		this.retryDelay = RETRY_BASE_MS
		this.kickUploader()
	}

	/** Restart synchronization after a failure (recording already stopped;
	 * every chunk is still local — this can never lose audio). */
	retrySync(): void {
		if (this.totalChunks === null) return
		this.state.error = ''
		this.state.errorKind = ''
		this.state.phase = 'syncing'
		this.retryDelay = RETRY_BASE_MS
		this.stopMonitors()
		this.startMonitors()
		clientLog('info', 'sync_retry_requested')
		this.kickUploader()
	}

	private kickUploader(): void {
		if (this.wakeUploader) this.wakeUploader()
		else this.runUploader()
	}

	private startMonitors(): void {
		window.addEventListener('online', this.onlineListener)
		this.heartbeatTimer = window.setInterval(() => void this.sendHeartbeat(), HEARTBEAT_MS)
		this.storageTimer = window.setInterval(() => void this.checkStorage(), STORAGE_CHECK_MS)
		void this.sendHeartbeat()
	}

	private stopMonitors(): void {
		window.removeEventListener('online', this.onlineListener)
		window.clearInterval(this.heartbeatTimer)
		window.clearInterval(this.storageTimer)
	}

	private async sendHeartbeat(): Promise<void> {
		try {
			let freeMb: number | undefined
			if (navigator.storage?.estimate) {
				const { quota, usage } = await navigator.storage.estimate()
				if (quota) freeMb = Math.round(((quota - (usage ?? 0)) / 1024 / 1024) * 10) / 10
			}
			await recorderApi.heartbeat(this.token, {
				recording_id: this.state.recordingId || undefined,
				recording_active: this.state.phase === 'recording',
				local_chunks: this.state.localChunks,
				acked_chunks: this.state.ackedChunks,
				storage_ok: !this.state.storageError,
				storage_free_mb: freeMb,
				battery_level: await readBatteryLevel(),
				local_recordings: await idb.countFor(this.assemblyId),
			})
		} catch {
			/* offline — heartbeats resume when the network does */
		}
	}

	private async checkStorage(): Promise<void> {
		try {
			if (!navigator.storage?.estimate) return
			const { quota, usage } = await navigator.storage.estimate()
			if (quota) {
				const freeMb = (quota - (usage ?? 0)) / 1024 / 1024
				this.state.lowStorage = freeMb < LOW_STORAGE_MB
				if (this.state.lowStorage) clientLog('warn', 'storage_low', { freeMb: Math.round(freeMb) })
			}
		} catch {
			/* estimate unavailable */
		}
	}

	private enqueueChunk(blob: Blob): void {
		const seq = this.seq
		this.seq += 1
		this.chunkPipeline = this.chunkPipeline
			.then(async () => {
				const buffer = await blob.arrayBuffer()
				const sha256 = await sha256Hex(buffer)
				await idb.putChunk({
					key: `${this.state.recordingId}:${seq}`,
					recordingId: this.state.recordingId,
					seq,
					blob,
					sha256,
					sizeBytes: blob.size,
					createdAt: Date.now(),
					acked: false,
					attempts: 0,
				})
				this.state.localChunks += 1
				clientLog('info', 'chunk_saved_local', { seq, bytes: blob.size })
				this.kickUploader()
			})
			.catch((error) => {
				// Local persistence failure is the HIGHEST severity problem (brief §22)
				this.state.storageError = true
				this.state.error = `Local storage error: ${error}`
				clientLog('error', 'chunk_save_failed', { seq, error: String(error).slice(0, 200) })
			})
	}

	private async runUploader(): Promise<void> {
		if (this.uploaderActive) return
		this.uploaderActive = true
		try {
			for (;;) {
				const pending = (await idb.chunksFor(this.state.recordingId)).filter((c) => !c.acked)
				if (pending.length === 0) {
					if (this.totalChunks !== null) break // finished and everything acked
					if (this.state.phase !== 'recording' && this.state.phase !== 'finishing') break
					await this.idleWait(1000)
					continue
				}
				const chunk = pending[0]
				try {
					await recorderApi.uploadChunk(
						this.token, this.state.recordingId, chunk.seq, chunk.blob, chunk.sha256,
					)
					chunk.acked = true
					chunk.attempts += 1
					await idb.putChunk(chunk)
					this.state.ackedChunks += 1
					this.state.uploadOnline = true
					this.state.uploadFailure = ''
					this.state.retryInMs = 0
					this.retryDelay = RETRY_BASE_MS
					clientLog('info', 'chunk_acked', { seq: chunk.seq, attempts: chunk.attempts })
				} catch (error) {
					// while the mic is live we keep retrying no matter what (audio
					// preservation first); once only syncing remains, a definitive
					// server rejection is a dead end — surface it instead of looping
					if (this.state.phase === 'syncing' && isGoneError(error)) {
						this.state.phase = 'failed'
						this.state.error = error instanceof Error ? error.message : String(error)
						this.state.errorKind = 'gone'
						clientLog('error', 'sync_gone', { error: this.state.error.slice(0, 160) })
						this.stopMonitors()
						return
					}
					this.state.uploadOnline = false
					// a server fault is not the table's connection dropping —
					// telling them "network unavailable" sends people to check
					// the WiFi when nothing is wrong at their end
					this.state.uploadFailure =
						error instanceof RecorderApiError && error.status >= 500 ? 'server' : 'network'
					chunk.attempts += 1
					await idb.putChunk(chunk)
					clientLog('warn', 'chunk_upload_failed', {
						seq: chunk.seq, attempts: chunk.attempts, error: String(error).slice(0, 160),
					})
					this.state.retryInMs = this.retryDelay
					await this.idleWait(this.retryDelay)
					this.retryDelay = Math.min(this.retryDelay * 2, RETRY_MAX_MS)
				}
			}
			if (this.totalChunks !== null) await this.sendComplete()
		} finally {
			this.uploaderActive = false
		}
	}

	/** Sleep that a manual retry / online event can cut short. */
	private idleWait(ms: number): Promise<void> {
		return new Promise((resolve) => {
			const timer = window.setTimeout(() => {
				this.wakeUploader = null
				resolve()
			}, ms)
			this.wakeUploader = () => {
				window.clearTimeout(timer)
				this.wakeUploader = null
				resolve()
			}
		})
	}

	async finish(): Promise<void> {
		if (!this.mediaRecorder || this.stopRequested) return
		this.stopRequested = true
		this.state.phase = 'finishing'
		clientLog('info', 'finish_requested')

		await new Promise<void>((resolve) => {
			this.mediaRecorder!.onstop = () => resolve()
			this.mediaRecorder!.stop()
		})
		this.stream?.getTracks().forEach((track) => track.stop())

		// wait until the final dataavailable chunk is persisted
		await this.chunkPipeline
		this.totalChunks = this.seq
		this.state.phase = 'syncing'

		const recordings = await idb.getRecordings()
		const meta = recordings.find((r) => r.recordingId === this.state.recordingId)
		if (meta) {
			meta.finishedAt = Date.now()
			meta.totalChunks = this.totalChunks
			await idb.putRecording(meta)
		}
		this.kickUploader()
	}

	private async sendComplete(): Promise<void> {
		if (this.totalChunks === null || this.totalChunks === 0) {
			this.state.phase = 'failed'
			this.state.error = 'No audio was captured'
			return
		}
		// a busy server (transcription running, restart, rate limit) must never
		// dead-end a finished recording — retry with backoff for up to ~5 min
		const deadline = Date.now() + 5 * 60_000
		try {
			for (;;) {
				try {
					let result = await recorderApi.complete(this.token, this.state.recordingId, this.totalChunks)
					// server-detected gaps: resend those chunks from local storage, then retry
					while (result.missing_sequences.length > 0) {
						clientLog('warn', 'server_missing_chunks', { missing: result.missing_sequences.length })
						const chunks = await idb.chunksFor(this.state.recordingId)
						for (const seqNumber of result.missing_sequences) {
							const chunk = chunks.find((c) => c.seq === seqNumber)
							if (!chunk) throw new Error(`Chunk ${seqNumber} is missing locally too`)
							await recorderApi.uploadChunk(
								this.token, this.state.recordingId, chunk.seq, chunk.blob, chunk.sha256,
							)
						}
						result = await recorderApi.complete(this.token, this.state.recordingId, this.totalChunks)
					}
					this.state.uploadOnline = true
					await this.pollUntilProcessed()
					return
				} catch (error) {
					if (!isGoneError(error) && isTransientError(error) && Date.now() < deadline) {
						this.state.uploadOnline = false
						clientLog('warn', 'sync_retrying', {
							error: String(error).slice(0, 160), delayMs: this.retryDelay,
						})
						await this.idleWait(this.retryDelay)
						this.retryDelay = Math.min(this.retryDelay * 2, RETRY_MAX_MS)
						continue
					}
					this.state.error = error instanceof Error ? error.message : String(error)
					this.state.errorKind = isGoneError(error) ? 'gone' : 'transient'
					this.state.phase = 'failed'
					clientLog('error', 'sync_failed', { error: this.state.error.slice(0, 200) })
					return
				}
			}
		} finally {
			this.stopMonitors()
		}
	}

	private async pollUntilProcessed(): Promise<void> {
		// anything at or past AUDIO_READY means the audio is validated and safe
		// (auto-transcription can move the state onward within seconds)
		const SUCCESS = new Set([
			'AUDIO_READY', 'TRANSCRIBING', 'TRANSCRIBED', 'TRANSCRIPTION_FAILED',
			'ANALYZING', 'READY_FOR_REVIEW', 'REVIEWED', 'ANALYSIS_FAILED',
		])
		let failedSince = 0
		for (let i = 0; i < 150; i += 1) {
			try {
				const status = await recorderApi.recordingStatus(this.token, this.state.recordingId)
				failedSince = 0
				this.state.uploadOnline = true
				this.state.serverState = status.state
				if (SUCCESS.has(status.state) || status.state === 'AUDIO_INVALID') {
					this.state.phase = SUCCESS.has(status.state) ? 'done' : 'failed'
					if (SUCCESS.has(status.state)) {
						clientLog('info', 'recording_synchronized', { recordingId: this.state.recordingId })
						await this.markServerComplete()
					} else {
						this.state.error = `Server could not validate the audio (${status.error_code})`
						clientLog('error', 'audio_invalid', { errorCode: status.error_code })
					}
					return
				}
			} catch (error) {
				// a blip (busy server, dropped connection) must not fail a
				// recording whose chunks are already uploaded — keep polling
				if (isGoneError(error)) throw error
				this.state.uploadOnline = false
				if (failedSince === 0) failedSince = Date.now()
				if (Date.now() - failedSince > 5 * 60_000) throw error
				clientLog('warn', 'status_poll_failed', { error: String(error).slice(0, 120) })
			}
			await new Promise((resolve) => setTimeout(resolve, 2000))
		}
		// Five minutes of polling and the server never reported a state at or
		// past AUDIO_READY. Every chunk was acknowledged, so the upload itself
		// is finished — but nothing has confirmed the assembled audio, and
		// saying so is not the same as the server saying so. Calling this
		// 'done' told the table "uploaded and validated by the server" and
		// then offered to delete the only other copy, on no evidence at all.
		this.state.phase = 'uploaded'
		clientLog('warn', 'server_confirmation_timed_out', {
			recordingId: this.state.recordingId,
			lastServerState: this.state.serverState,
		})
	}

	/** Ask the server once whether it has finished with this recording.
	 *
	 * The 'uploaded' screen offers this: every chunk was acknowledged but the
	 * server had not confirmed the assembled audio before the poll window
	 * closed. A later check often succeeds — assembly may simply have been
	 * queued behind other tables.
	 */
	async recheckServerState(): Promise<void> {
		const SETTLED = new Set([
			'AUDIO_READY', 'TRANSCRIBING', 'TRANSCRIBED', 'TRANSCRIPTION_FAILED',
			'ANALYZING', 'READY_FOR_REVIEW', 'REVIEWED', 'ANALYSIS_FAILED',
		])
		try {
			const status = await recorderApi.recordingStatus(this.token, this.state.recordingId)
			this.state.uploadOnline = true
			this.state.serverState = status.state
			if (SETTLED.has(status.state)) {
				this.state.phase = 'done'
				clientLog('info', 'recording_synchronized', { recordingId: this.state.recordingId })
				await this.markServerComplete()
			} else if (status.state === 'AUDIO_INVALID') {
				this.state.phase = 'failed'
				this.state.error = `Server could not validate the audio (${status.error_code})`
			}
		} catch (error) {
			this.state.uploadOnline = false
			clientLog('warn', 'recheck_failed', { error: String(error).slice(0, 120) })
		}
	}

	private async markServerComplete(): Promise<void> {
		const recordings = await idb.getRecordings()
		const meta = recordings.find((r) => r.recordingId === this.state.recordingId)
		if (meta) {
			meta.serverComplete = true
			await idb.putRecording(meta)
		}
	}
}

/** The phone's battery, 0–1, or undefined where the browser will not say.
 *
 * The whole reason this feature exists is a phone dying mid-round: knowing it
 * is at 8% while there is still time to swap it beats every recovery path
 * downstream. Chromium on Android exposes this; Safari and Firefox removed it
 * on fingerprinting grounds, so absence is common and means only "unknown".
 */
export async function readBatteryLevel(): Promise<number | undefined> {
	try {
		const getBattery = (
			navigator as Navigator & { getBattery?: () => Promise<{ level: number }> }
		).getBattery
		if (!getBattery) return undefined
		const battery = await getBattery.call(navigator)
		return typeof battery?.level === 'number' ? battery.level : undefined
	} catch {
		return undefined // permissions policy, or an unsupported context
	}
}

/** Explicit local cleanup of fully synchronized recordings (done screen). */
export async function clearSynchronizedRecordings(assemblyId?: string): Promise<number> {
	const recordings = await idb.getRecordings()
	let cleared = 0
	for (const recording of recordings) {
		// serverComplete is the whole safety of this: only audio the server has
		// confirmed it holds is ever removed, so this can never destroy the
		// last copy of anything.
		if (!recording.serverComplete) continue
		// and only this assembly's, or audio predating the field — clearing one
		// event must not quietly delete another's from a citizen's own phone
		if (assemblyId && recording.assemblyId && recording.assemblyId !== assemblyId) continue
		await idb.deleteChunksFor(recording.recordingId)
		await idb.deleteRecording(recording.recordingId)
		cleared += 1
	}
	return cleared
}
