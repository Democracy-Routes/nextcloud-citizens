<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import {
	mdiBroadcast,
	mdiCheckCircle,
	mdiCloudUploadOutline,
	mdiDatabaseOutline,
	mdiTrayFull,
} from '@mdi/js'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import SvgIcon from '../../components/ui/SvgIcon.vue'
import { useI18n } from 'vue-i18n'
import { recorderApi, type JoinResult, type RoundInfo } from '../api'
import { MicrophoneError } from '../errors'
import { idb } from '../idb'
import { useWakeLock } from '../useWakeLock'
import { clearSynchronizedRecordings, RecorderEngine } from '../engine'

const props = defineProps<{ session: JoinResult; round: RoundInfo }>()
const emit = defineEmits<{
	exit: []
	nextRound: [round: RoundInfo]
	viewReport: []
	/** recording could not be started for THIS round — armed must not
	 * immediately send the table straight back in, whatever the cause */
	startFailed: [roundId: string]
	/** nothing is being captured any more: uploaded, done, or failed. The
	 * parent needs this because the screen stays mounted long after the
	 * microphone stops. */
	settled: []
}>()

const { t } = useI18n()

const engine = new RecorderEngine()
const state = engine.state
const now = ref(Date.now())
const confirmFinish = ref(false)
const level = ref(0)
const startError = ref('')
const roundEnded = ref(false)
const finishCountdown = ref(0)
const keepTalking = ref(false)
const nextStartCountdown = ref(0)
const clearedNote = ref('')

const orchestrated = props.session.assembly.recording_mode === 'orchestrated'

// How long "Keep talking" holds off the auto-finish before it re-arms. Long
// enough to finish a thought; bounded, so a table that taps it and walks away
// still ends — the latch used to be permanent, and the recording ran into an
// ENDED round until battery or storage gave out.
const KEEP_TALKING_REPRIEVE_MS = 120_000
let countdownTimer = 0
let reprieveTimer = 0
let nextStartTimer = 0

// orchestrated: the facilitator ended the round → auto-finish after a short
// cancellable countdown so a last sentence can be completed
function beginFinishCountdown(): void {
	if (countdownTimer || keepTalking.value) return
	finishCountdown.value = 15
	countdownTimer = window.setInterval(() => {
		finishCountdown.value -= 1
		if (finishCountdown.value <= 0) {
			window.clearInterval(countdownTimer)
			countdownTimer = 0
			void finishRecording()
		}
	}, 1000)
}

function cancelFinishCountdown(): void {
	window.clearInterval(countdownTimer)
	countdownTimer = 0
	finishCountdown.value = 0
	// a reprieve, not a permanent latch: after the window the auto-finish
	// re-arms (the next ENDED poll or duration check restarts the countdown),
	// so an abandoned table is still finished
	keepTalking.value = true
	window.clearTimeout(reprieveTimer)
	reprieveTimer = window.setTimeout(() => {
		keepTalking.value = false
	}, KEEP_TALKING_REPRIEVE_MS)
}
const showLive = ref(true)
const liveLines = ref<Array<{ t: number; text: string; speaker?: number | null }>>([])
const liveChecked = ref(false)
const captionsBox = ref<HTMLElement | null>(null)
const nextRound = ref<RoundInfo | null>(null)
const reportAvailable = ref(false)
const reportOpenCountdown = ref(0)
const tableSummaries = ref<Array<{ position: number; title: string; summary: string }>>([])

let reportOpenTimer = 0

// orchestrated: when the organizer publishes the report and no round is left,
// the table follows automatically after a short visible countdown
function beginReportAutoOpen(): void {
	if (reportOpenTimer) return
	reportOpenCountdown.value = 3
	reportOpenTimer = window.setInterval(() => {
		reportOpenCountdown.value -= 1
		if (reportOpenCountdown.value <= 0) {
			window.clearInterval(reportOpenTimer)
			reportOpenTimer = 0
			emit('viewReport')
		}
	}, 1000)
}
const qbarOpen = ref(false)
const techOpen = ref(false)

// consecutive caption fragments from the same speaker flow together as one
// block; a new block starts when the speaker changes
const captionBlocks = computed(() => {
	const blocks: Array<{ speaker: number | null; text: string }> = []
	for (const line of liveLines.value) {
		const speaker = line.speaker ?? null
		const last = blocks[blocks.length - 1]
		if (last && last.speaker === speaker) last.text += ' ' + line.text
		else blocks.push({ speaker, text: line.text })
	}
	return blocks
})

let nextRoundTimer = 0

// After finishing, the device is locked: it only offers the next un-recorded
// round once the facilitator activates it (no accidental re-recordings).
function watchForNextRound(): void {
	if (nextRoundTimer) return
	const poll = async () => {
		try {
			const status = await recorderApi.status(props.session.session_token)
			reportAvailable.value = status.report_available ?? false
			// the done screen auto-records the next round, so the table counts
			// as armed on the organizer's readiness indicator
			if (orchestrated && status.rounds.some((r) => !r.recorded_state)) {
				// local_recordings included: without it the finished screen —
				// where phones sit at the end of an assembly — reported nothing
				// about what it still held, so purge coverage read "unknown"
				const held = await idb.countFor(props.session.assembly.id)
				void recorderApi
					.heartbeat(props.session.session_token, {
						recording_active: false,
						armed: true,
						local_chunks: 0,
						acked_chunks: 0,
						storage_ok: true,
						local_recordings: held,
					})
					.catch(() => undefined)
			}
			// report auto-open: published by the organizer, or (independent)
			// every table finished every round — both surface here
			if (reportAvailable.value && !status.rounds.some((r) => !r.recorded_state)) {
				beginReportAutoOpen()
			}
			// orchestrated waits for the facilitator to activate the next round;
			// independent tables advance to any round they haven't recorded yet
			nextRound.value = orchestrated
				? (status.rounds.find(
						(r) => r.status === 'ACTIVE' && !r.recorded_state && r.id !== props.round.id,
					) ?? null)
				: (status.rounds.find((r) => !r.recorded_state && r.id !== props.round.id) ?? null)
			// this table's per-round AI summaries for the final screen
			tableSummaries.value = status.rounds
				.filter((r) => r.recorded_state)
				.map((r) => ({ position: r.position, title: r.title, summary: r.table_summary ?? '' }))
			// orchestrated: the armed table auto-starts the next round after a
			// short visible countdown (consent was given when arming)
			if (orchestrated && nextRound.value && !nextStartTimer) {
				nextStartCountdown.value = 3
				nextStartTimer = window.setInterval(() => {
					nextStartCountdown.value -= 1
					// Clear on reaching zero WHATEVER nextRound now holds. Gating
					// the clear on nextRound being set leaked the interval when
					// the round disappeared mid-countdown, and the stale timer
					// then started a recording with no warning the moment some
					// later poll set nextRound again.
					if (nextStartCountdown.value > 0) return
					stopNextStartTimer()
					if (nextRound.value) emit('nextRound', nextRound.value)
				}, 1000)
			}
		} catch {
			/* offline — retried on next tick */
		}
	}
	void poll()
	nextRoundTimer = window.setInterval(() => void poll(), 10_000)
}

function stopNextStartTimer(): void {
	window.clearInterval(nextStartTimer)
	nextStartTimer = 0
}

// the countdown is announcing a round that no longer exists: stop announcing it
watch(nextRound, (round) => {
	if (!round) stopNextStartTimer()
})

let clockTimer = 0
let levelTimer = 0
let roundPollTimer = 0
let livePollTimer = 0
let audioContext: AudioContext | null = null

const elapsed = computed(() => {
	if (!state.startedAt) return '00:00'
	const seconds = Math.max(0, Math.floor((now.value - state.startedAt) / 1000))
	const minutes = Math.floor(seconds / 60)
	return `${String(minutes).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
})

const pendingChunks = computed(() => state.localChunks - state.ackedChunks)

watch(liveLines, () => {
	void nextTick(() => {
		captionsBox.value?.scrollTo({ top: captionsBox.value.scrollHeight })
	})
})

watch(
	() => state.phase,
	(phase) => {
		if (phase === 'done' || phase === 'uploaded') watchForNextRound()
		if (['done', 'uploaded', 'failed'].includes(phase)) emit('settled')
	},
)

// Not just while recording: the finished screen polls for the next round and
// auto-starts it, so letting the phone sleep here means missing that too.
useWakeLock(() =>
	['recording', 'finishing', 'syncing', 'done', 'uploaded'].includes(state.phase),
)

onMounted(async () => {
	clockTimer = window.setInterval(() => {
		now.value = Date.now()
		// independent tables run on the round's planned time: when it elapses,
		// finish automatically (with the same cancellable grace countdown)
		if (
			!orchestrated &&
			state.phase === 'recording' &&
			!keepTalking.value &&
			state.startedAt &&
			now.value - state.startedAt >= props.round.duration_minutes * 60_000
		) {
			roundEnded.value = true
			beginFinishCountdown()
		}
	}, 500)
	await beginRecording()
	const stream = engine.mediaStream
	if (stream) {
		audioContext = new AudioContext()
		const analyser = audioContext.createAnalyser()
		analyser.fftSize = 512
		audioContext.createMediaStreamSource(stream).connect(analyser)
		const samples = new Uint8Array(analyser.fftSize)
		levelTimer = window.setInterval(() => {
			analyser.getByteTimeDomainData(samples)
			let peak = 0
			for (const value of samples) peak = Math.max(peak, Math.abs(value - 128))
			level.value = Math.min(100, Math.round((peak / 128) * 160))
		}, 120)
	}
	roundPollTimer = window.setInterval(async () => {
		if (state.phase !== 'recording') return
		try {
			const status = await recorderApi.status(props.session.session_token)
			const current = status.rounds.find((r) => r.id === props.round.id)
			if (current && current.status === 'ENDED') {
				roundEnded.value = true
				if (orchestrated) beginFinishCountdown()
			}
		} catch {
			/* offline — round state resumes with the network */
		}
	}, 5000)
	startLivePoll()
})

onBeforeUnmount(() => {
	window.clearInterval(clockTimer)
	window.clearInterval(levelTimer)
	window.clearInterval(roundPollTimer)
	window.clearInterval(livePollTimer)
	window.clearInterval(nextRoundTimer)
	window.clearInterval(countdownTimer)
	window.clearInterval(nextStartTimer)
	window.clearInterval(reportOpenTimer)
	window.clearTimeout(reprieveTimer)
	audioContext?.close()
	// Abandon live capture if the screen leaves while still recording — a purge
	// arriving mid-round, or an exit. Without this the MediaRecorder, the mic
	// tracks and the engine's own timers kept running with nothing owning them.
	// Don't touch a legitimate in-flight sync (finishing/syncing/uploaded).
	if (state.phase === 'recording') engine.stop()
})

function startLivePoll(): void {
	if (livePollTimer) return
	const poll = async () => {
		if (!showLive.value || !state.recordingId || state.phase !== 'recording') return
		try {
			const result = await recorderApi.liveTranscript(props.session.session_token, state.recordingId)
			liveLines.value = result.lines.slice(-40)
			liveChecked.value = true
		} catch {
			/* captions are best-effort */
		}
	}
	void poll()
	livePollTimer = window.setInterval(() => void poll(), 6000)
}

async function finishRecording(): Promise<void> {
	confirmFinish.value = false
	roundEnded.value = false
	window.clearTimeout(reprieveTimer)
	await engine.finish()
}

const startBusy = ref(false)
const startErrorIsMicrophone = ref(true)

/** Open the microphone. On failure, tell the parent which round failed.
 *
 * Without that the loop was: start fails -> "Back" -> ArmedScreen -> its poll
 * sees the round still ACTIVE -> emits start -> fails again, every five
 * seconds, with no way out for the table.
 */
async function beginRecording(): Promise<void> {
	startBusy.value = true
	startError.value = ''
	try {
		await engine.start(
			props.session.session_token,
			props.round.id,
			props.session.assembly.id,
			props.session.table_number,
		)
	} catch (error) {
		startError.value = error instanceof Error ? error.message : String(error)
		// A microphone problem is the phone's owner to fix; anything else — the
		// server refusing because this table is already recording, say — is not,
		// and telling them to check their permissions sends them after a
		// microphone that is working.
		startErrorIsMicrophone.value = error instanceof MicrophoneError
		emit('startFailed', props.round.id)
	} finally {
		startBusy.value = false
	}
}

async function retryMicrophone(): Promise<void> {
	await beginRecording()
}

const recheckBusy = ref(false)

async function recheck(): Promise<void> {
	recheckBusy.value = true
	try {
		await engine.recheckServerState()
	} finally {
		recheckBusy.value = false
	}
}

async function clearSynced(): Promise<void> {
	const cleared = await clearSynchronizedRecordings(props.session.assembly.id)
	clearedNote.value = `${cleared} synchronized recording(s) removed from this phone.`
}
</script>

<template>
	<div class="rc-fill">
		<div class="rc-header">
			<span class="rc-table-badge">TABLE {{ session.table_number }}</span>
			<span v-if="state.phase === 'recording'" class="rc-live">RECORDING</span>
		</div>

		<div v-if="startError" class="rc-scroll">
			<div class="rc-alert">
				<strong>
					{{ startErrorIsMicrophone ? t('recorder.mic.failedTitle') : t('recorder.mic.serverTitle') }}
				</strong>
				<p style="margin: 8px 0 0">{{ startError }}</p>
				<p class="rc-muted" style="margin: 10px 0 0; font-size: 0.875rem">
					{{ startErrorIsMicrophone ? t('recorder.mic.guidance') : t('recorder.mic.serverHelp') }}
				</p>
				<button
					class="rc-btn rc-primary"
					style="margin-top: 14px"
					:disabled="startBusy"
					@click="retryMicrophone">
					{{
						startBusy
							? t('recorder.mic.retrying')
							: startErrorIsMicrophone
								? t('recorder.mic.retry')
								: t('recorder.mic.serverRetry')
					}}
				</button>
				<button class="rc-btn rc-subtle" style="margin-top: 8px" @click="emit('exit')">
					{{ t('recorder.mic.back') }}
				</button>
			</div>
		</div>

		<template v-else-if="state.phase === 'recording' || state.phase === 'finishing'">
			<button class="rc-qbar" :class="{ 'rc-qbar--open': qbarOpen }" @click="qbarOpen = !qbarOpen">
				<span class="rc-eyebrow" style="margin: 0">
					{{ t('recorder.common.roundOf', { position: round.position, total: session.rounds.length }) }}
				</span>
				<p class="rc-qbar__q">{{ round.question || round.title }}</p>
			</button>

			<div class="rc-scroll">
			<div class="rc-timer-wrap">
				<div class="rc-timer-ring" :class="{ 'rc-timer-ring--live': state.phase === 'recording' }">
					<span class="rc-timer">{{ elapsed }}</span>
					<span class="rc-timer-label">{{ state.phase === 'recording' ? 'recording' : 'stopping…' }}</span>
				</div>
			</div>

			<div class="rc-level"><div class="rc-level-fill" :style="{ width: level + '%' }"></div></div>

			<button class="rc-techbar" @click="techOpen = !techOpen">
				<span class="rc-techbar__item">
					<span class="rc-dot" :class="{ 'rc-dot--bad': state.storageError }"></span>
					{{
						state.storageError
							? t('recorder.recording.storageErrorShort')
							: t('recorder.recording.audioSafe')
					}}
				</span>
				<span class="rc-techbar__item">
					<span class="rc-dot" :class="{ 'rc-dot--warn': !state.uploadOnline }"></span>
					{{ state.uploadOnline ? 'Uploading' : 'Offline' }}
				</span>
				<span class="rc-techbar__item">
					<span class="rc-dot" :class="{ 'rc-dot--warn': pendingChunks > 3 }"></span>
					{{ pendingChunks }} pending
				</span>
			</button>

			<div v-if="techOpen" class="rc-card" style="padding: 8px 18px">
				<div class="rc-status-row">
					<span class="rc-status-row__label">
						<SvgIcon :path="mdiDatabaseOutline" :size="19" style="color: var(--rc-muted)" />
						{{ t('recorder.recording.localAudio') }}
					</span>
					<span :class="state.storageError ? 'rc-bad' : 'rc-ok'">
						{{ state.storageError ? t('recorder.recording.storageErrorBanner') : '✓ SAFE' }}
					</span>
				</div>
				<div class="rc-status-row">
					<span class="rc-status-row__label">
						<SvgIcon :path="mdiCloudUploadOutline" :size="19" style="color: var(--rc-muted)" />
						{{ t('recorder.recording.serverUpload') }}
					</span>
					<span :class="state.uploadOnline ? 'rc-ok' : 'rc-warn'">
						{{ state.uploadOnline ? '✓' : 'OFFLINE' }}
					</span>
				</div>
				<div class="rc-status-row">
					<span class="rc-status-row__label">
						<SvgIcon :path="mdiTrayFull" :size="19" style="color: var(--rc-muted)" />
						{{ t('recorder.recording.pendingUpload') }}
					</span>
					<span :class="pendingChunks > 3 ? 'rc-warn' : ''">{{ pendingChunks }} chunks</span>
				</div>
			</div>

			<div v-if="state.storageError" class="rc-alert">
				<strong>{{ t('recorder.recording.storageErrorTitle') }}</strong><br />
				{{ t('recorder.recording.storageErrorBody') }}
			</div>
			<div v-else-if="!state.uploadOnline" class="rc-note">
				<template v-if="state.uploadFailure === 'server'">
					{{ t('recorder.recording.serverBusy') }}
				</template>
				<template v-else>
					{{ t('recorder.recording.offline') }}
				</template>
				<button class="rc-btn" style="margin-top: 10px" @click="engine.retryNow()">{{ t('recorder.recording.retryUpload') }}</button>
			</div>
			<p v-else class="rc-muted rc-center" style="font-size: 0.845rem">
				{{ t('recorder.recording.keepOpen') }}
			</p>

			<div v-if="state.lowStorage" class="rc-alert">
				{{ t('recorder.recording.lowStorage') }}
			</div>

			<div v-if="roundEnded && state.phase === 'recording'" class="rc-note">
				<!-- the ended/time-up line stands alone; the countdown is its own
				     sentence, so the two no longer splice into "The round has
				     ended. — finishing in 6 s." -->
				<strong style="display: block">
					{{ orchestrated ? t('recorder.recording.roundEnded') : t('recorder.recording.timeUp') }}
				</strong>
				<template v-if="finishCountdown > 0">
					<span>{{ t('recorder.recording.finishingIn', { seconds: finishCountdown }) }}</span>
					<button class="rc-btn" style="margin-top: 10px" @click="cancelFinishCountdown">
						{{ t('recorder.recording.keepTalking') }}
					</button>
				</template>
				<template v-else>
					<span>{{ t('recorder.recording.finishQuestion') }}</span>
					<button class="rc-btn rc-primary" style="margin-top: 10px" @click="finishRecording">
						{{ t('recorder.recording.finish') }}
					</button>
				</template>
			</div>

			<template v-if="state.phase === 'recording'">
				<div v-if="showLive" class="rc-card">
					<p class="rc-eyebrow">{{ t('recorder.recording.liveTranscript') }}</p>
					<p v-if="captionBlocks.length === 0" class="rc-muted" style="font-size: 0.875rem; margin: 0">
						{{
							liveChecked
								? t('recorder.recording.captionsUnavailable')
								: t('recorder.recording.waitingCaptions')
						}}
					</p>
					<div v-else ref="captionsBox" class="rc-captions">
						<div v-for="(block, index) in captionBlocks" :key="index" class="rc-caption">
							<span v-if="block.speaker !== null" class="rc-caption__speaker">
								Speaker {{ block.speaker + 1 }}
							</span>
							{{ block.text }}
						</div>
					</div>
				</div>
				<button class="rc-btn rc-subtle" @click="showLive = !showLive">
					<SvgIcon :path="mdiBroadcast" :size="18" />
					{{
						showLive
							? t('recorder.recording.hideTranscript')
							: t('recorder.recording.showTranscript')
					}}
				</button>
			</template>
			</div>

			<div v-if="state.phase === 'recording'" class="rc-actions">
				<button v-if="!confirmFinish" class="rc-btn" @click="confirmFinish = true">
					{{ t('recorder.recording.finishButton') }}
				</button>
				<template v-else>
					<div class="rc-note" style="margin: 0 0 8px">{{ t('recorder.recording.confirmFinish') }}</div>
					<button class="rc-btn rc-primary" style="margin-top: 0" @click="finishRecording">{{ t('recorder.recording.confirmFinishYes') }}</button>
					<button class="rc-btn rc-subtle" @click="confirmFinish = false">
						{{ t('recorder.recording.keepRecording') }}
					</button>
				</template>
			</div>
		</template>

		<template v-else-if="state.phase === 'syncing'">
			<div class="rc-scroll">
				<div v-if="state.micLost" class="rc-alert" role="alert">
					{{ t('recorder.recording.micLost') }}
				</div>
				<div class="rc-hero">
					<div class="rc-hero__icon"><SvgIcon :path="mdiCloudUploadOutline" :size="44" style="color: var(--rc-blue)" /></div>
					<h1>Synchronizing</h1>
					<p class="rc-muted" style="margin-top: 10px; font-size: 1rem">
						<span style="font-variant-numeric: tabular-nums">{{ state.ackedChunks }} / {{ state.localChunks }}</span>
						{{ t('recorder.recording.chunksUploaded') }}
						<template v-if="state.serverState"><br />Server: {{ state.serverState }}</template>
					</p>
					<div v-if="!state.uploadOnline" class="rc-note" style="text-align: left">
						{{ t('recorder.recording.retrying') }}
						{{ t('recorder.recording.audioSafe') }}
					</div>
				</div>
			</div>
		</template>

		<template v-else-if="state.phase === 'done' || state.phase === 'uploaded'">
			<div class="rc-scroll">
				<div class="rc-hero">
					<div
						class="rc-hero__icon"
						:class="state.phase === 'done' ? 'rc-hero__icon--ok' : ''">
						<SvgIcon
							:path="state.phase === 'done' ? mdiCheckCircle : mdiCloudUploadOutline"
							:size="52" />
					</div>
					<h1>
						{{ state.phase === 'done' ? t('recorder.done.title') : t('recorder.uploaded.title') }}
					</h1>
					<p v-if="state.phase === 'done'" class="rc-muted" style="margin-top: 10px">
						{{ t('recorder.done.body', { position: round.position }) }}
					</p>
					<p v-else class="rc-muted" style="margin-top: 10px">
						{{ t('recorder.uploaded.body', { position: round.position }) }}
					</p>
					<div v-if="state.phase === 'uploaded'" class="rc-note" style="margin-top: 14px">
						<button class="rc-btn rc-subtle" :disabled="recheckBusy" @click="recheck">
							{{ recheckBusy ? t('recorder.uploaded.checking') : t('recorder.uploaded.check') }}
						</button>
					</div>
					<p v-if="clearedNote" class="rc-muted">{{ clearedNote }}</p>

					<div v-if="nextRound && orchestrated" class="rc-note" style="text-align: left; margin-top: 20px">
						<strong>{{ t('recorder.recording.nextStarted', { position: nextRound.position }) }}</strong>
						<template v-if="nextStartCountdown > 0">
							{{ t('recorder.recording.nextCountdown', { seconds: nextStartCountdown }) }}
						</template>
						<br />
						{{ nextRound.question || nextRound.title }}
					</div>
					<div v-else-if="nextRound" class="rc-card" style="text-align: left; margin-top: 20px">
						<p class="rc-eyebrow" style="margin-bottom: 4px">
							{{ t('recorder.recording.nextRound', { position: nextRound.position, minutes: nextRound.duration_minutes }) }}
						</p>
						<p class="rc-question" style="margin: 0">
							{{ nextRound.question || nextRound.title }}
						</p>
						<p class="rc-muted" style="margin: 10px 0 0; font-size: 0.845rem">
							{{ t('recorder.recording.takeABreak') }}
						</p>
					</div>
					<div v-else-if="reportOpenCountdown > 0" class="rc-note" style="text-align: left; margin-top: 20px">
						<strong>{{ t('recorder.recording.reportReady') }}</strong>
						{{ t('recorder.recording.openingIn', { seconds: reportOpenCountdown }) }}
					</div>
					<template v-else>
						<div v-if="tableSummaries.length" class="rc-card" style="text-align: left; margin-top: 20px">
							<p class="rc-eyebrow">{{ t('recorder.recording.allRounds') }}</p>
							<template v-for="entry in tableSummaries" :key="entry.position">
								<p class="rc-eyebrow" style="margin: 10px 0 2px; color: var(--rc-blue)">
									{{ t('recorder.preflight.roundSummary', { position: entry.position }) }}
								</p>
								<p v-if="entry.summary" style="font-size: 0.875rem; margin: 0">{{ entry.summary }}</p>
								<p v-else class="rc-muted" style="font-size: 0.845rem; margin: 0">
									{{ t('recorder.preflight.analyzing') }}
								</p>
							</template>
						</div>
						<p class="rc-muted rc-center" style="margin-top: 14px; font-size: 0.845rem">
							{{ t('recorder.recording.reportPending') }}
						</p>
					</template>
				</div>
			</div>

			<div class="rc-actions">
				<button
					v-if="nextRound && !orchestrated"
					class="rc-btn rc-record"
					style="margin-top: 0"
					@click="emit('nextRound', nextRound)">
					{{ t('recorder.recording.startNext', { position: nextRound.position }) }}
				</button>
				<button v-if="reportAvailable" class="rc-btn rc-primary" @click="emit('viewReport')">
					{{ t('recorder.armed.viewReport') }}
				</button>
				<!-- only when the SERVER confirmed it: this deletes the copy that
				     would otherwise be the last one -->
				<button
					v-if="!clearedNote && state.phase === 'done'"
					class="rc-linkbtn"
					@click="clearSynced">
					{{ t('recorder.recording.clearAudio') }}
				</button>
			</div>
		</template>

		<template v-else-if="state.phase === 'failed'">
			<div class="rc-scroll">
				<div class="rc-alert" style="margin-top: 30px">
					<strong>{{ t('recorder.recording.syncFailed') }}</strong><br />{{ state.error }}
					<br /><br />
					{{ t('recorder.recording.syncFailedSafe') }}
					{{ t('recorder.recording.tryAgainLater') }}
				</div>
			</div>
			<div class="rc-actions">
				<button class="rc-btn rc-primary" style="margin-top: 0" @click="engine.retrySync()">
					{{ t('recorder.common.tryAgain') }}
				</button>
				<button class="rc-btn rc-subtle" @click="emit('exit')">Back</button>
			</div>
		</template>
	</div>
</template>
