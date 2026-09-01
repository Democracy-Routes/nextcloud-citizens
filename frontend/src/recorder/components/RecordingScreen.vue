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
import { recorderApi, type JoinResult, type RoundInfo } from '../api'
import { useWakeLock } from '../useWakeLock'
import { clearSynchronizedRecordings, RecorderEngine } from '../engine'

const props = defineProps<{ session: JoinResult; round: RoundInfo }>()
const emit = defineEmits<{
	exit: []
	nextRound: [round: RoundInfo]
	viewReport: []
	/** the microphone could not be opened for THIS round — armed must not
	 * immediately send the table straight back in */
	micFailed: [roundId: string]
}>()

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

let countdownTimer = 0
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
	keepTalking.value = true
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
				void recorderApi
					.heartbeat(props.session.session_token, {
						recording_active: false,
						armed: true,
						local_chunks: 0,
						acked_chunks: 0,
						storage_ok: true,
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
	audioContext?.close()
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
	await engine.finish()
}

const startBusy = ref(false)

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
		await engine.start(props.session.session_token, props.round.id)
	} catch (error) {
		startError.value = error instanceof Error ? error.message : String(error)
		emit('micFailed', props.round.id)
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
	const cleared = await clearSynchronizedRecordings()
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
				<strong>The microphone could not be started.</strong>
				<p style="margin: 8px 0 0">{{ startError }}</p>
				<p class="rc-muted" style="margin: 10px 0 0; font-size: 0.875rem">
					If the browser asked for microphone permission and it was refused,
					allow it in the site settings — tap the icon to the left of the web
					address, then Permissions, then Microphone — and try again. You do
					not need to reload this page.
				</p>
				<button
					class="rc-btn rc-primary"
					style="margin-top: 14px"
					:disabled="startBusy"
					@click="retryMicrophone">
					{{ startBusy ? 'Trying…' : 'Try the microphone again' }}
				</button>
				<button class="rc-btn rc-subtle" style="margin-top: 8px" @click="emit('exit')">
					Back
				</button>
			</div>
		</div>

		<template v-else-if="state.phase === 'recording' || state.phase === 'finishing'">
			<button class="rc-qbar" :class="{ 'rc-qbar--open': qbarOpen }" @click="qbarOpen = !qbarOpen">
				<span class="rc-eyebrow" style="margin: 0">Round {{ round.position }} of {{ session.rounds.length }}</span>
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
					{{ state.storageError ? 'Storage error' : 'Audio safe' }}
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
						Local audio
					</span>
					<span :class="state.storageError ? 'rc-bad' : 'rc-ok'">
						{{ state.storageError ? '✕ STORAGE ERROR' : '✓ SAFE' }}
					</span>
				</div>
				<div class="rc-status-row">
					<span class="rc-status-row__label">
						<SvgIcon :path="mdiCloudUploadOutline" :size="19" style="color: var(--rc-muted)" />
						Server upload
					</span>
					<span :class="state.uploadOnline ? 'rc-ok' : 'rc-warn'">
						{{ state.uploadOnline ? '✓' : 'OFFLINE' }}
					</span>
				</div>
				<div class="rc-status-row">
					<span class="rc-status-row__label">
						<SvgIcon :path="mdiTrayFull" :size="19" style="color: var(--rc-muted)" />
						Pending upload
					</span>
					<span :class="pendingChunks > 3 ? 'rc-warn' : ''">{{ pendingChunks }} chunks</span>
				</div>
			</div>

			<div v-if="state.storageError" class="rc-alert">
				<strong>LOCAL STORAGE ERROR</strong><br />
				Recording can no longer be safely stored. Please notify the facilitator immediately.
			</div>
			<div v-else-if="!state.uploadOnline" class="rc-note">
				<template v-if="state.uploadFailure === 'server'">
					The server is busy — the recording continues safely on this phone and will upload
					by itself. Nothing is lost. Keep this page open.
				</template>
				<template v-else>
					Network unavailable — the recording continues safely on this phone and will upload
					when the connection returns. Keep this page open.
				</template>
				<button class="rc-btn" style="margin-top: 10px" @click="engine.retryNow()">Retry upload now</button>
			</div>
			<p v-else class="rc-muted rc-center" style="font-size: 13.5px">
				Keep this page open while the table is recording.
			</p>

			<div v-if="state.lowStorage" class="rc-alert">
				Phone storage is getting low. Notify the facilitator after this round.
			</div>

			<div v-if="roundEnded && state.phase === 'recording'" class="rc-note">
				<template v-if="finishCountdown > 0">
					<strong>
						{{ orchestrated ? 'The round has ended' : 'Time is up for this round' }}
						— finishing in {{ finishCountdown }} s.
					</strong>
					<button class="rc-btn" style="margin-top: 10px" @click="cancelFinishCountdown">
						Keep talking
					</button>
				</template>
				<template v-else>
					<strong>{{ orchestrated ? 'The round has ended.' : 'Time is up for this round.' }}</strong>
					Finish recording?
					<button class="rc-btn rc-primary" style="margin-top: 10px" @click="finishRecording">
						Finish and synchronize
					</button>
				</template>
			</div>

			<template v-if="state.phase === 'recording'">
				<div v-if="showLive" class="rc-card">
					<p class="rc-eyebrow">Live transcript — provisional</p>
					<p v-if="captionBlocks.length === 0" class="rc-muted" style="font-size: 14px; margin: 0">
						{{ liveChecked ? 'Live captions temporarily unavailable. Recording continues safely.' : 'Waiting for captions…' }}
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
					{{ showLive ? 'Hide live transcript' : 'Show live transcript' }}
				</button>
			</template>
			</div>

			<div v-if="state.phase === 'recording'" class="rc-actions">
				<button v-if="!confirmFinish" class="rc-btn" @click="confirmFinish = true">
					Finish recording
				</button>
				<template v-else>
					<div class="rc-note" style="margin: 0 0 8px">Finish and synchronize this table's recording?</div>
					<button class="rc-btn rc-primary" style="margin-top: 0" @click="finishRecording">Yes, finish and synchronize</button>
					<button class="rc-btn rc-subtle" @click="confirmFinish = false">Keep recording</button>
				</template>
			</div>
		</template>

		<template v-else-if="state.phase === 'syncing'">
			<div class="rc-scroll">
				<div class="rc-hero">
					<div class="rc-hero__icon"><SvgIcon :path="mdiCloudUploadOutline" :size="44" style="color: var(--rc-blue)" /></div>
					<h1>Synchronizing</h1>
					<p class="rc-muted" style="margin-top: 10px; font-size: 16px">
						<span style="font-variant-numeric: tabular-nums">{{ state.ackedChunks }} / {{ state.localChunks }}</span>
						chunks uploaded
						<template v-if="state.serverState"><br />Server: {{ state.serverState }}</template>
					</p>
					<div v-if="!state.uploadOnline" class="rc-note" style="text-align: left">
						Connection problem or busy server — retrying automatically.
						The audio is safe on this phone. Keep this page open.
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
					<h1>{{ state.phase === 'done' ? 'Recording synchronized' : 'Recording uploaded' }}</h1>
					<p v-if="state.phase === 'done'" class="rc-muted" style="margin-top: 10px">
						Round {{ round.position }} is complete for this table.
						The recording was uploaded and validated by the server.
					</p>
					<p v-else class="rc-muted" style="margin-top: 10px">
						Round {{ round.position }} is complete for this table. Every part of
						the recording was uploaded and accepted, but the server has not
						finished processing it yet. Keep this phone's copy until it has.
					</p>
					<div v-if="state.phase === 'uploaded'" class="rc-note" style="margin-top: 14px">
						<button class="rc-btn rc-subtle" :disabled="recheckBusy" @click="recheck">
							{{ recheckBusy ? 'Checking…' : 'Check again' }}
						</button>
					</div>
					<p v-if="clearedNote" class="rc-muted">{{ clearedNote }}</p>

					<div v-if="nextRound && orchestrated" class="rc-note" style="text-align: left; margin-top: 20px">
						<strong>Round {{ nextRound.position }} has started.</strong>
						<template v-if="nextStartCountdown > 0">
							Recording begins in {{ nextStartCountdown }} s…
						</template>
						<br />
						{{ nextRound.question || nextRound.title }}
					</div>
					<div v-else-if="nextRound" class="rc-card" style="text-align: left; margin-top: 20px">
						<p class="rc-eyebrow" style="margin-bottom: 4px">
							Next: Round {{ nextRound.position }} · {{ nextRound.duration_minutes }} minutes
						</p>
						<p class="rc-question" style="margin: 0">
							{{ nextRound.question || nextRound.title }}
						</p>
						<p class="rc-muted" style="margin: 10px 0 0; font-size: 13.5px">
							Take a break if you need one — recording starts when you tap the button.
						</p>
					</div>
					<div v-else-if="reportOpenCountdown > 0" class="rc-note" style="text-align: left; margin-top: 20px">
						<strong>The assembly report is ready.</strong>
						Opening in {{ reportOpenCountdown }} s…
					</div>
					<template v-else>
						<div v-if="tableSummaries.length" class="rc-card" style="text-align: left; margin-top: 20px">
							<p class="rc-eyebrow">This table has completed all rounds</p>
							<template v-for="entry in tableSummaries" :key="entry.position">
								<p class="rc-eyebrow" style="margin: 10px 0 2px; color: var(--rc-blue)">
									Round {{ entry.position }} — your table's AI summary
								</p>
								<p v-if="entry.summary" style="font-size: 14px; margin: 0">{{ entry.summary }}</p>
								<p v-else class="rc-muted" style="font-size: 13.5px; margin: 0">
									Analyzing your discussion…
								</p>
							</template>
						</div>
						<p class="rc-muted rc-center" style="margin-top: 14px; font-size: 13.5px">
							Keep this page open — the assembly report appears here when every table
							has finished or the organizer publishes it.
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
					We're ready — Start Round {{ nextRound.position }}
				</button>
				<button v-if="reportAvailable" class="rc-btn rc-primary" @click="emit('viewReport')">
					View assembly report
				</button>
				<!-- only when the SERVER confirmed it: this deletes the copy that
				     would otherwise be the last one -->
				<button
					v-if="!clearedNote && state.phase === 'done'"
					class="rc-linkbtn"
					@click="clearSynced">
					Clear synchronized audio from this phone
				</button>
			</div>
		</template>

		<template v-else-if="state.phase === 'failed'">
			<div class="rc-scroll">
				<div class="rc-alert" style="margin-top: 30px">
					<strong>Synchronization did not finish:</strong><br />{{ state.error }}
					<br /><br />
					The audio is safely stored on this phone — nothing is lost.
					Try again in a moment.
				</div>
			</div>
			<div class="rc-actions">
				<button class="rc-btn rc-primary" style="margin-top: 0" @click="engine.retrySync()">
					Try again
				</button>
				<button class="rc-btn rc-subtle" @click="emit('exit')">Back</button>
			</div>
		</template>
	</div>
</template>
