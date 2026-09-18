// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/*
 * Recording engine: one MediaRecorder session, periodic chunks written to
 * IndexedDB FIRST, then uploaded asynchronously with acknowledgment tracking,
 * exponential-backoff retry, heartbeats and crash recovery.
 * The network is never required to preserve audio (brief §17–§20).
 */

import { reactive } from 'vue'
import { RecorderApiError, recorderApi, type RecordingStatus } from './api'
import { isGoneError, isTransientError, MicrophoneError } from './errors'
import { idb, type StoredRecording } from './idb'
import { clientLog } from './logger'
import { sha256Blob, sha256Hex } from './sha'
import { transferChunk } from './transfer'
import { t } from '../i18n'

// ~10 s chunks by default (brief §17.2); overridable via ?chunkms= for tests
export const CHUNK_INTERVAL_MS = (() => {
	const override = Number(new URLSearchParams(window.location.search).get('chunkms'))
	return Number.isFinite(override) && override >= 250 ? override : 10_000
})()
/** Server states at or past AUDIO_READY: the audio is validated and safe.
 *
 * Mirrors COMPLETED_STATES in citizens/services/recording.py — this was
 * hand-copied in two methods and nothing kept the copies agreeing. */
export const COMPLETED_STATES = new Set([
	'AUDIO_READY', 'TRANSCRIBING', 'TRANSCRIBED', 'TRANSCRIPTION_FAILED',
	'ANALYZING', 'READY_FOR_REVIEW', 'REVIEWED', 'ANALYSIS_FAILED',
])

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
	/** total_chunks the server last reported having assembled — null while it is
	 * mid-assembly, so a mismatch against local length is only meaningful once set */
	serverManifestChunks: number | null
	error: string
	/** 'gone' = the server definitively no longer knows this recording/session
	 * (deleted assembly, reset instance) — retrying can never succeed */
	errorKind: '' | 'gone' | 'transient' | 'rejected'
	/** The OS took the microphone away mid-round (a call, another app). What
	 * was captured has been finished and is syncing — but the table must be
	 * told, because from their side the screen just said RECORDING. */
	micLost: boolean
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
		serverManifestChunks: null,
		error: '',
		errorKind: '',
		micLost: false,
	})

	private token = ''
	/** so the heartbeat can report how much of THIS assembly is still here */
	private assemblyId: string | undefined
	private stream: MediaStream | null = null
	private mediaRecorder: MediaRecorder | null = null
	private seq = 0
	private totalChunks: number | null = null
	// serializes async chunk persistence so sequence order matches event order
	private chunkPipeline: Promise<void> = Promise.resolve()
	private uploaderActive = false
	private stopRequested = false
	/** Capture was abandoned (screen left, purge) — tear down, do not upload. */
	private abandoned = false
	private uploadBlocked = false
	private completionReady = false
	private unsavedChunks = new Map<number, Blob>()
	private retryDelay = RETRY_BASE_MS
	private wakeUploader: (() => void) | null = null
	private heartbeatTimer = 0
	private storageTimer = 0
	private onlineListener = () => {
		clientLog('info', 'network_online')
		this.retryDelay = RETRY_BASE_MS
		this.kickUploader()
	}

	async start(
		token: string,
		roundId: string,
		assemblyId: string,
		tableNumber: number,
	): Promise<void> {
		this.assemblyId = assemblyId
		this.token = token
		const mimeType = pickMimeType()
		if (!mimeType) throw new Error(t('recorder.engine.noFormat'))

		try {
			this.stream = await navigator.mediaDevices.getUserMedia({
				audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: true },
			})
		} catch (error) {
			// only THIS is a microphone problem; the call below can fail for
			// reasons the phone's owner can do nothing about
			throw new MicrophoneError(error instanceof Error ? error.message : String(error))
		}
		const started = await recorderApi.start(token, roundId, mimeType)
		this.state.recordingId = started.recording_id
		this.state.startedAt = Date.now()
		this.state.phase = 'recording'
		clientLog('info', 'recording_started', { recordingId: started.recording_id, mimeType })

		await idb.putRecording({
			recordingId: started.recording_id,
			assemblyId,
			roundId,
			// this recording's table, not the phone's current one: a phone can
			// record table 3, be handed to table 7 later, and still hold the
			// first recording's audio locally
			tableNumber,
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
		// The OS can take the microphone at any moment — an incoming call,
		// another app, a Bluetooth headset dropping. Nothing listened for it:
		// the track ended, capture stopped, and the screen went on saying
		// RECORDING and "safe" while nothing was being recorded. Finishing
		// immediately keeps everything captured so far and tells the table.
		this.mediaRecorder.onerror = () => void this.abortForLostMicrophone('recorder_error')
		for (const track of this.stream.getAudioTracks()) {
			track.onended = () => void this.abortForLostMicrophone('track_ended')
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
		this.assemblyId = recording.assemblyId
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
		if (this.abandoned) return
		this.completionReady = true
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
	async retrySync(): Promise<void> {
		if (this.totalChunks === null) return
		try {
			for (const [seq, blob] of this.unsavedChunks) {
				await idb.putChunk({ key: `${this.state.recordingId}:${seq}`, recordingId: this.state.recordingId,
					seq, blob, sha256: await sha256Blob(blob), sizeBytes: blob.size,
					createdAt: Date.now(), acked: false, attempts: 0 })
				this.unsavedChunks.delete(seq)
				this.state.localChunks++
			}
			const meta = (await idb.getRecordings()).find((r) => r.recordingId === this.state.recordingId)
			if (!meta) throw new Error(t('recorder.engine.metadataMissing'))
			meta.totalChunks = this.totalChunks
			meta.finishedAt = meta.finishedAt ?? Date.now()
			meta.captureIncomplete = await this.persistedPrefixLength() !== this.totalChunks
			await idb.putRecording(meta)
			if (meta.captureIncomplete) {
				this.state.error = t('recorder.safety.incomplete')
				return
			}
		} catch {
			this.state.storageError = true
			this.state.error = t('recorder.safety.storageUnavailable')
			return
		}
		// Every chunk acked and a 409 already told us the server is past
		// /complete: re-posting it cannot succeed (the 409 is deterministic
		// once ASSEMBLING begins). Poll for the assembly instead of firing the
		// same doomed request on every tap of "Try again".
		const allAcked = (await idb.chunksFor(this.state.recordingId)).every((c) => c.acked)
		if (allAcked && this.state.serverState === 'ASSEMBLING') {
			this.state.error = ''
			this.state.errorKind = ''
			this.state.storageError = false
			this.state.phase = 'syncing'
			this.stopMonitors()
			this.startMonitors()
			clientLog('info', 'sync_retry_as_poll')
			const pollDeadline = Date.now() + 5 * 60_000
			for (;;) {
				try {
					await this.pollUntilProcessed()
					return
				} catch (pollError) {
					if (await this.settlePollFailure(pollError, pollDeadline)) return
				}
			}
		}
		this.state.error = ''
		this.state.storageError = false
		this.state.errorKind = ''
		this.state.phase = 'syncing'
		this.uploadBlocked = false
		this.completionReady = true
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
				local_recordings: this.assemblyId ? await idb.countFor(this.assemblyId) : undefined,
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
		this.unsavedChunks.set(seq, blob)
		this.chunkPipeline = this.chunkPipeline
			.then(async () => {
				const sha256 = blob.size > 5 * 1024 * 1024
					? await sha256Blob(blob) : await sha256Hex(await blob.arrayBuffer())
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
				this.unsavedChunks.delete(seq)
				clientLog('info', 'chunk_saved_local', { seq, bytes: blob.size })
				this.kickUploader()
			})
			.catch((error) => {
				// Local persistence failure is the HIGHEST severity problem (brief §22)
				this.state.storageError = true
				this.state.error = t('recorder.engine.storageError', { error: String(error) })
				clientLog('error', 'chunk_save_failed', { seq, error: String(error).slice(0, 200) })
			})
	}

	private async runUploader(): Promise<void> {
		if (this.uploaderActive || this.uploadBlocked || this.abandoned) return
		this.uploaderActive = true
		try {
			for (;;) {
				const pending = (await idb.chunksFor(this.state.recordingId)).filter((c) => !c.acked)
				if (this.abandoned) break
				if (pending.length === 0) {
					if (this.totalChunks !== null) break // finished and everything acked
					if (this.state.phase !== 'recording' && this.state.phase !== 'finishing') break
					await this.idleWait(1000)
					continue
				}
				const chunk = pending[0]
				try {
					await transferChunk(this.token, this.state.recordingId, chunk)
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
					if (error instanceof RecorderApiError && error.status === 409 && this.totalChunks !== null) {
						try {
							await this.markServerComplete(await recorderApi.recordingStatus(this.token, this.state.recordingId))
							this.state.phase = 'done'
							this.stopMonitors()
							return
						} catch { /* conflict is not proof that all local audio arrived */ }
					}
					if (!isTransientError(error)) {
						this.uploadBlocked = true
						this.state.errorKind = isGoneError(error) ? 'gone' : 'rejected'
						this.state.error = error instanceof Error ? error.message : String(error)
						this.state.uploadFailure = 'server'
						this.state.uploadOnline = false
						if (this.state.phase !== 'recording' && this.state.phase !== 'finishing') {
							this.state.phase = 'failed'
							this.stopMonitors()
						}
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
			if (!this.abandoned && this.completionReady && this.totalChunks !== null) await this.sendComplete()
		} catch (error) {
			this.state.storageError = true
			this.state.error = t('recorder.safety.storageUnavailable')
			clientLog('error', 'upload_storage_failed', { error: String(error).slice(0, 160) })
			if (this.state.phase !== 'recording' && this.state.phase !== 'finishing') this.state.phase = 'failed'
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

	/** Stop the microphone and background work when the screen is left.
	 * Keep persisted audio and accept the final dataavailable event locally;
	 * unlike finish(), this does not declare completion to the server. */
	stop(): void {
		if (this.abandoned) return
		this.abandoned = true
		// stop late chunk/track events from re-entering
		if (this.mediaRecorder) {
			// stop() emits one final blob. Persist it even when this screen left.
			this.mediaRecorder.onerror = null
			try {
				if (this.mediaRecorder.state !== 'inactive') this.mediaRecorder.stop()
			} catch {
				/* already inactive */
			}
		}
		for (const track of this.stream?.getTracks() ?? []) {
			track.onended = null
			track.stop()
		}
		this.stream = null
		this.stopMonitors()
		// let the uploader loop's idleWait resolve so it sees `abandoned` and exits
		if (this.wakeUploader) this.wakeUploader()
	}

	async finish(): Promise<void> {
		if (!this.mediaRecorder || this.stopRequested || this.abandoned) return
		this.stopRequested = true
		this.state.phase = 'finishing'
		clientLog('info', 'finish_requested')

		await new Promise<void>((resolve) => {
			this.mediaRecorder!.onstop = () => resolve()
			try {
				this.mediaRecorder!.stop()
			} catch {
				// already inactive — the OS took the microphone. stopRequested
				// is latched by now, so throwing here wedged the screen in a
				// button-less 'finishing' state; what was captured still syncs.
				resolve()
			}
		})
		this.stream?.getTracks().forEach((track) => track.stop())

		// wait until the final dataavailable chunk is persisted
		await this.chunkPipeline
		// Never call a prefix the complete recording. Retain failed writes in
		// memory and keep the page open so they can be saved or downloaded.
		this.totalChunks = this.seq
		let prefix: number
		try {
			prefix = await this.persistedPrefixLength()
		} catch {
			this.state.storageError = true
			this.state.error = t('recorder.safety.storageUnavailable')
			this.state.phase = 'failed'
			this.stopMonitors()
			return
		}
		if (prefix < this.seq) {
			clientLog('error', 'chunks_lost_locally', {
				captured: this.seq, contiguous: prefix,
			})
		}
		this.state.phase = 'syncing'

		try {
			const recordings = await idb.getRecordings()
			const meta = recordings.find((r) => r.recordingId === this.state.recordingId)
			if (!meta) throw new Error(t('recorder.engine.metadataMissing'))
			meta.finishedAt = Date.now()
			meta.totalChunks = this.totalChunks
			meta.captureIncomplete = prefix !== this.seq || this.unsavedChunks.size > 0
			await idb.putRecording(meta)
		} catch {
			this.state.storageError = true
			this.state.error = t('recorder.safety.storageUnavailable')
			this.state.phase = 'failed'
			this.stopMonitors()
			return
		}
		if (prefix !== this.seq || this.unsavedChunks.size > 0 || this.uploadBlocked) {
			this.state.phase = 'failed'
			this.state.errorKind = this.state.errorKind || 'rejected'
			this.state.error = this.state.error || t('recorder.safety.storageUnavailable')
			this.stopMonitors()
			return
		}
		this.completionReady = true
		this.kickUploader()
	}

	/** The microphone died under us: salvage what was captured, loudly. */
	private async abortForLostMicrophone(cause: string): Promise<void> {
		if (this.state.phase !== 'recording' || this.state.micLost) return
		this.state.micLost = true
		clientLog('error', 'microphone_lost', { cause, recordingId: this.state.recordingId })
		try {
			await this.finish()
		} catch (error) {
			clientLog('error', 'microphone_lost_finish_failed', {
				error: String(error).slice(0, 160),
			})
		}
	}

	/** How many chunks, counting from 0 with no gap, are really stored. */
	private async persistedPrefixLength(): Promise<number> {
		const chunks = await idb.chunksFor(this.state.recordingId)
		const have = new Set(chunks.map((chunk) => chunk.seq))
		let length = 0
		while (have.has(length)) length += 1
		return length
	}

	private async sendComplete(): Promise<void> {
		if (this.totalChunks === null || this.totalChunks === 0) {
			this.state.phase = 'failed'
			this.state.error = t('recorder.engine.noAudio')
			return
		}
		// a busy server (transcription running, restart, rate limit) must never
		// dead-end a finished recording — retry with backoff for up to ~5 min
		const deadline = Date.now() + 5 * 60_000
		try {
			for (; !this.abandoned;) {
				try {
					let result = await recorderApi.complete(this.token, this.state.recordingId, this.totalChunks)
					// server-detected gaps: resend those chunks from local storage, then retry
					while (result.missing_sequences.length > 0) {
						clientLog('warn', 'server_missing_chunks', { missing: result.missing_sequences.length })
						const chunks = await idb.chunksFor(this.state.recordingId)
						let truncatedTo: number | null = null
						for (const seqNumber of result.missing_sequences) {
							const chunk = chunks.find((c) => c.seq === seqNumber)
							if (!chunk) {
								// Do not shrink the declaration to hide missing audio.
								truncatedTo = truncatedTo === null ? seqNumber : Math.min(truncatedTo, seqNumber)
								continue
							}
							await transferChunk(this.token, this.state.recordingId, chunk)
						}
						if (truncatedTo !== null) {
							clientLog('error', 'complete_truncated_to_gap', {
								declared: this.totalChunks, salvaged: truncatedTo,
							})
							throw new RecorderApiError(409, t('recorder.safety.incomplete'))
						}
						result = await recorderApi.complete(this.token, this.state.recordingId, this.totalChunks)
					}
					this.state.uploadOnline = true
					await this.pollUntilProcessed()
					return
			} catch (error) {
				if (await this.completedDespiteConflict(error)) {
					clientLog('info', 'complete_conflict_already_finished', {
						recordingId: this.state.recordingId, serverState: this.state.serverState,
					})
					this.state.uploadOnline = true
					this.state.error = ''
					this.state.errorKind = ''
					this.state.phase = 'syncing' // ASSEMBLING while the manifest is verified
					// A 409 means the server HAS this recording: the deadline
					// that bounds retrying lost uploads must not turn waiting
					// into a failure. Keep polling until AUDIO_READY
					// (markServerComplete verifies the manifest then) or
					// AUDIO_INVALID (the real answer), surfacing "syncing" the
					// whole time rather than stranding the phone on a dead-end
					// failed screen that re-POSTs a deterministic 409 on every
					// tap of Try again.
					const pollDeadline = Date.now() + 5 * 60_000
					for (;;) {
						try {
							await this.pollUntilProcessed()
							return
						} catch (pollError) {
							if (await this.settlePollFailure(pollError, pollDeadline)) return
						}
					}
				}
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
				this.state.errorKind = isGoneError(error) ? 'gone' : isTransientError(error) ? 'transient' : 'rejected'
				this.state.phase = 'failed'
				clientLog('error', 'sync_failed', { error: this.state.error.slice(0, 200) })
				return
			}
			}
		} finally {
			this.stopMonitors()
		}
	}

	/** Was that a "this recording is already finished" refusal?
	 *
	 * /complete 409s once the recording is ASSEMBLING or beyond — which is
	 * exactly where a reload during the "Synchronizing" screen lands: the
	 * server took the last chunk, started assembling, and the recovered phone
	 * re-posts /complete. Treating that 409 as a failure told the table its
	 * sync had failed for a recording the server had already finished, and
	 * because serverComplete was never set, the phone re-entered the recovery
	 * screen on every boot forever — with the purge blocked behind it.
	 */
	private async completedDespiteConflict(error: unknown): Promise<boolean> {
		if (!(error instanceof RecorderApiError) || error.status !== 409) return false
		try {
			const status = await recorderApi.recordingStatus(this.token, this.state.recordingId)
			this.state.serverState = status.state
			return COMPLETED_STATES.has(status.state) || status.state === 'ASSEMBLING'
		} catch {
			return false
		}
	}

	/** pollUntilProcessed threw while the server HAS this recording: keep
	 * polling, or settle? Returns true once settled.
	 *
	 * Deterministic answers end it. A 409 out of markServerComplete means the
	 * server's OWN manifest failed verification — a prefix salvage (fewer
	 * chunks than this phone captured), or an equal-length manifest with a
	 * different hash or byte count — and no amount of re-polling changes what
	 * the server assembled. A gone session (401/403/404/410) cannot be polled
	 * back into existence. Only transient failures earn another look, and only
	 * until the deadline: past it the honest state is 'uploaded' — every chunk
	 * was acknowledged, nothing confirmed the assembled audio — exactly what
	 * pollUntilProcessed says when its own window closes.
	 *
	 * The first version of this loop exited only on the salvage case, so an
	 * equal-length mismatch or a revoked session re-asked the same question
	 * every three seconds forever, on a screen with no way to get the audio
	 * off the phone. Local audio was never at risk — serverComplete is set
	 * nowhere but after a full manifest match — but liveness was. */
	private async settlePollFailure(pollError: unknown, deadline: number): Promise<boolean> {
		if (this.abandoned || this.state.phase !== 'syncing') return true
		const message = pollError instanceof Error ? pollError.message : String(pollError)
		if (isGoneError(pollError)) {
			this.state.error = message
			this.state.errorKind = 'gone'
			this.state.phase = 'failed'
			clientLog('error', 'sync_failed', { error: message.slice(0, 200), kind: 'gone' })
			return true
		}
		if (!isTransientError(pollError)) {
			const serverChunks = this.state.serverManifestChunks
			const salvaged = pollError instanceof RecorderApiError && pollError.status === 409
				&& serverChunks !== null
				&& serverChunks < (await idb.chunksFor(this.state.recordingId)).length
			this.state.error = message
			this.state.errorKind = 'rejected'
			this.state.phase = 'failed'
			clientLog('warn', salvaged ? 'sync_failed_salvage' : 'sync_failed_unverified', {
				serverChunks,
			})
			return true
		}
		if (Date.now() >= deadline) {
			this.state.phase = 'uploaded'
			clientLog('warn', 'server_confirmation_timed_out', {
				recordingId: this.state.recordingId, lastServerState: this.state.serverState,
			})
			return true
		}
		await this.idleWait(RETRY_BASE_MS)
		return false
	}

	private async pollUntilProcessed(): Promise<void> {
		const SUCCESS = COMPLETED_STATES
		let failedSince = 0
		for (let i = 0; i < 150 && !this.abandoned; i += 1) {
			try {
				const status = await recorderApi.recordingStatus(this.token, this.state.recordingId)
				failedSince = 0
				this.state.uploadOnline = true
				this.state.serverState = status.state
				this.state.serverManifestChunks = status.total_chunks
				if (this.abandoned) return
				if (SUCCESS.has(status.state) || status.state === 'AUDIO_INVALID') {
					if (SUCCESS.has(status.state)) {
						clientLog('info', 'recording_synchronized', { recordingId: this.state.recordingId })
						await this.markServerComplete(status)
						this.state.phase = 'done'
					} else {
						this.state.phase = 'failed'
						this.state.error = t('recorder.engine.invalidAudio', { code: status.error_code })
						clientLog('error', 'audio_invalid', { errorCode: status.error_code })
					}
					return
				}
			} catch (error) {
				// a blip (busy server, dropped connection) must not fail a
				// recording whose chunks are already uploaded — keep polling
				if (isGoneError(error) || !isTransientError(error)) throw error
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
		if (this.abandoned) return
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
		const SETTLED = COMPLETED_STATES
		try {
			const status = await recorderApi.recordingStatus(this.token, this.state.recordingId)
			this.state.uploadOnline = true
			this.state.serverState = status.state
			if (SETTLED.has(status.state)) {
				clientLog('info', 'recording_synchronized', { recordingId: this.state.recordingId })
				await this.markServerComplete(status)
				this.state.phase = 'done'
			} else if (status.state === 'AUDIO_INVALID') {
				this.state.phase = 'failed'
				this.state.error = t('recorder.engine.invalidAudio', { code: status.error_code })
			}
		} catch (error) {
			this.state.uploadOnline = false
			if (!isTransientError(error)) {
				this.state.phase = 'failed'
				this.state.errorKind = isGoneError(error) ? 'gone' : 'rejected'
				this.state.error = error instanceof Error ? error.message : String(error)
			}
			clientLog('warn', 'recheck_failed', { error: String(error).slice(0, 120) })
		}
	}

	private async markServerComplete(status: RecordingStatus): Promise<void> {
		const recordings = await idb.getRecordings()
		const meta = recordings.find((r) => r.recordingId === this.state.recordingId)
		const chunks = await idb.chunksFor(this.state.recordingId)
		const manifest = chunks.map((c) => `${c.seq}:${c.sizeBytes}:${c.sha256}\n`).join('')
		const hash = await sha256Hex(new TextEncoder().encode(manifest).buffer)
		if (!meta || !chunks.length || this.unsavedChunks.size > 0 || meta.captureIncomplete
			|| !status.audio_available || !COMPLETED_STATES.has(status.state)
			|| meta.totalChunks !== chunks.length || chunks.some((c, i) => c.seq !== i)
			|| status.total_chunks !== chunks.length || status.audio_manifest_sha256 !== hash
			|| status.audio_manifest_bytes !== chunks.reduce((sum, c) => sum + c.sizeBytes, 0)) {
			throw new RecorderApiError(409, t('recorder.safety.unverified'))
		}
		if (meta) {
			meta.serverComplete = true
			meta.verificationVersion = 1
			await idb.putRecording(meta)
		}
	}

	async localAudio(): Promise<Blob> {
		const chunks = await idb.chunksFor(this.state.recordingId)
		const pieces = new Map(chunks.map((c) => [c.seq, c.blob]))
		for (const [seq, blob] of this.unsavedChunks) pieces.set(seq, blob)
		return new Blob([...pieces].sort(([a], [b]) => a - b).map(([, blob]) => blob),
			{ type: chunks[0]?.blob.type || 'audio/webm' })
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
		if (!recording.serverComplete || recording.verificationVersion !== 1 || recording.captureIncomplete) continue
		// only this assembly's. A legacy recording (no assemblyId) is left for
		// the unscoped done-screen clear — a specific assembly's purge must not
		// delete another event's audio from a citizen's own phone.
		if (assemblyId && recording.assemblyId !== assemblyId) continue
		await idb.deleteChunksFor(recording.recordingId)
		await idb.deleteRecording(recording.recordingId)
		cleared += 1
	}
	return cleared
}
