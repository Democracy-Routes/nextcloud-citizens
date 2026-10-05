<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import { roundHeading } from '../labels'
import {
	mdiCellphoneRemove,
	mdiClipboardTextOutline,
	mdiConsoleLine,
	mdiHandBackLeft,
	mdiMonitorEye,
	mdiPlay,
	mdiRefresh,
	mdiStop,
	mdiTextBoxOutline,
	mdiTextBoxPlusOutline,
} from '@mdi/js'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import { describeError } from '../errors'
import { relativeAge, timestamp } from '../format'
import { LIVE_MS } from '../composables/intervals'
import { usePolling } from '../composables/usePolling'
import type { AssemblyDetail, MonitorTable, RoundMonitor, SessionMessage, TranscriptData } from '../types'
import CzButton from './ui/CzButton.vue'
import CzConfirm from './ui/CzConfirm.vue'
import CzEmptyState from './ui/CzEmptyState.vue'
import CzFailureNote from './ui/CzFailureNote.vue'
import CzFreshness from './ui/CzFreshness.vue'
import CzSkeleton from './ui/CzSkeleton.vue'
import CzStatusPill from './ui/CzStatusPill.vue'
import SvgIcon from './ui/SvgIcon.vue'
import { toast } from './ui/toast'

const props = defineProps<{ assembly: AssemblyDetail }>()
const emit = defineEmits<{ changed: [] }>()

const roundId = ref(
	props.assembly.rounds.find((r) => r.status === 'ACTIVE')?.id ?? props.assembly.rounds[0]?.id ?? '',
)
const monitor = ref<RoundMonitor | null>(null)
const error = ref('')
const busy = ref(false)
const now = ref(Date.now())
const confirmStartUnready = ref(false)
const openTable = ref<number | null>(null)
const deviceLog = ref<string[]>([])
const transcript = ref<TranscriptData | null>(null)
const transcriptError = ref('')
const transcriptFor = ref('')

let clockTimer = 0

async function poll(): Promise<void> {
	if (!roundId.value) return
	const previous = monitor.value?.status
	monitor.value = await api.roundMonitor(roundId.value)
	error.value = ''
	// the poll is the only thing watching the round change state, so it has to
	// be what tells the rest of the app — otherwise the header pill, the
	// sidebar and the Rounds tab stay on whatever they last heard
	if (previous && previous !== monitor.value.status) emit('changed')
	void loadMessages()
}

/* ---- the facilitator's voice: "5 minutes left" to every table, or one ----
 * A message rides the phones' status poll; each phone reports when it has
 * shown it, which is the "delivered 9/10" here. Nothing stops a recording. */
const messages = ref<SessionMessage[]>([])
const messagesOpen = ref(false)
const messageText = ref('')
const messageTarget = ref<number | null>(null)
const messageBusy = ref(false)

async function loadMessages(): Promise<void> {
	if (!roundId.value) return
	try {
		messages.value = await api.roundMessages(roundId.value)
	} catch {
		/* an older server, or a blink: the row simply shows what it last had */
	}
}

async function sendMessage(data: Parameters<typeof api.sendMessage>[1]): Promise<void> {
	if (!roundId.value || messageBusy.value) return
	messageBusy.value = true
	try {
		await api.sendMessage(roundId.value, { ...data, target_table_number: messageTarget.value })
		messageText.value = ''
		await loadMessages()
	} catch (err) {
		error.value = describeError(err).message
	} finally {
		messageBusy.value = false
	}
}

/** The organizer has seen a table's hand: the row goes calm on the next poll,
 * the phone reads it on its own poll and says so. */
function acknowledgeHelp(table: MonitorTable): void {
	const request = table.help_request
	if (!request) return
	void run(() => api.acknowledgeHelp(request.id), `Table ${table.number}: acknowledged`)
}

function clockOf(iso: string): string {
	return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function sendCustom(): void {
	const text = messageText.value.trim()
	if (text) void sendMessage({ kind: 'CUSTOM', text })
}

function deliveryText(message: SessionMessage): string {
	const total = message.seen_by.length + message.not_seen_by.length
	if (!total) return 'no table in this session'
	const missing = message.not_seen_by.length
	if (!missing) return `Delivered ${total}/${total}`
	const names = message.not_seen_by.map((n) => `Table ${n}`).join(', ')
	return `Delivered ${message.seen_by.length}/${total} · ${names} not yet`
}

const recentMessages = computed(() => messages.value.slice(0, 3))

// keeps polling while hidden: this is the live view, and a facilitator
// switching to another tab for ten seconds should not come back to stale data
const polling = usePolling(poll, { intervalMs: LIVE_MS, pauseWhenHidden: false })

onMounted(() => {
	clockTimer = window.setInterval(() => (now.value = Date.now()), 1000)
})

onBeforeUnmount(() => {
	window.clearInterval(clockTimer)
})

watch(roundId, () => {
	monitor.value = null
	void polling.refresh()
})

/** A table more than this far behind the earliest one is worth pointing at. */
const DRIFT_WARNING_S = 60

function startedAt(table: MonitorTable): number | null {
	const started = table.recording?.started_at
	return started ? new Date(started).getTime() : null
}

/** How long THIS table has been recording, mm:ss. */
function tableElapsed(table: MonitorTable): string {
	const started = startedAt(table)
	if (started === null || table.recording?.state !== 'RECORDING') return ''
	const seconds = Math.max(0, Math.floor((now.value - started) / 1000))
	return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
}

/** Seconds this table started after the earliest table still recording. */
function tableDrift(table: MonitorTable): number {
	const started = startedAt(table)
	if (started === null) return 0
	const others = (monitor.value?.tables ?? [])
		.filter((t) => t.recording?.state === 'RECORDING')
		.map(startedAt)
		.filter((t): t is number => t !== null)
	return others.length ? (started - Math.min(...others)) / 1000 : 0
}

/** How long the facilitator gets to react once the round's time is up.
 *
 * Long enough to notice and press Extend, short enough that the round actually
 * ends. The phones then run their own 15s "Keep talking" countdown, so a table
 * mid-sentence still gets the last word. */
const GRACE_SECONDS = 60

/** Minutes added by pressing Extend.
 *
 * Held here rather than written to the round: the stored duration is what the
 * assembly was PLANNED for, and rewriting it would quietly edit the record of
 * what was run. The cost is that a page reload forgets an extension and offers
 * the choice again, which is the safe direction to fail. */
const EXTEND_MINUTES = 5
const extraMinutes = ref(0)
const autoEndCancelled = ref(false)

/** Seconds until the round's planned end. Negative once it has overrun. */
const secondsLeft = computed(() => {
	if (!monitor.value || monitor.value.status !== 'ACTIVE' || !monitor.value.started_at) return null
	const endAt =
		new Date(monitor.value.started_at).getTime() +
		(monitor.value.duration_minutes + extraMinutes.value) * 60_000
	return Math.floor((endAt - now.value) / 1000)
})

function clock(seconds: number): string {
	const whole = Math.abs(seconds)
	return `${String(Math.floor(whole / 60)).padStart(2, '0')}:${String(whole % 60).padStart(2, '0')}`
}

const remaining = computed(() => {
	const left = secondsLeft.value
	if (left === null) return ''
	// no longer clamped at zero: a round that has run over says so, rather than
	// sitting at 00:00 looking like it just finished
	return left < 0 ? `+${clock(left)}` : clock(left)
})

/** Time is up and nobody has extended or ended it yet. */
const overrunning = computed(() => secondsLeft.value !== null && secondsLeft.value <= 0)

/** When the grace window closes, as a wall-clock time — or 0 while not armed.
 *
 * Measured from when THIS TAB first observes the overrun, never from the
 * round's planned end. The previous version derived it from the planned end,
 * which meant a tab mounted onto a round already a minute over computed zero
 * on its first poll and ended the round about a second later, grace buttons
 * flashing past — F5 or a tab-switch was enough. The facilitator gets the
 * full window from the moment their screen could actually show it. */
const graceEndsAt = ref(0)
const autoEndFired = ref(false)

/** Seconds before this round ends by itself, for the countdown text. */
const autoEndIn = computed(() => {
	if (!overrunning.value || autoEndCancelled.value || graceEndsAt.value === 0) return null
	return Math.max(0, Math.ceil((graceEndsAt.value - now.value) / 1000))
})

// Rounds were ending only when a human clicked, so they ended at different
// times across tables — reported by participants as unfair and confusing. This
// ends them on time while leaving the facilitator in charge of the exception.
//
// Driven from the 1 Hz tick, not a watch on the countdown reaching zero: that
// was a single edge, and if `busy` happened to be true at that one tick the
// auto-end was lost forever while the bar promised "ending in 0s". A tick that
// finds the deadline passed just tries again next second. Orchestrated only —
// independent tables run on their own schedule and their phones already
// auto-finish; ending the round under them would be a silent, uncancellable
// interruption with none of this UI visible.
watch(now, () => {
	// facilitator-led (orchestrated and plenary) run the auto-end; independent does not
	if (monitor.value?.recording_mode === 'independent') return
	if (!overrunning.value || autoEndCancelled.value) {
		graceEndsAt.value = 0
		autoEndFired.value = false
		return
	}
	if (graceEndsAt.value === 0) {
		graceEndsAt.value = now.value + GRACE_SECONDS * 1000
		return
	}
	if (
		!autoEndFired.value &&
		now.value >= graceEndsAt.value &&
		monitor.value?.status === 'ACTIVE' &&
		!busy.value
	) {
		autoEndFired.value = true
		endRound()
	}
})

function extendRound(): void {
	extraMinutes.value += EXTEND_MINUTES
	// extending moves the planned end forward, so `overrunning` drops and the
	// grace state resets itself on the next tick
	toast(`Session extended by ${EXTEND_MINUTES} minutes`)
}

// a new round starts its own clock
watch(roundId, () => {
	extraMinutes.value = 0
	autoEndCancelled.value = false
	graceEndsAt.value = 0
	autoEndFired.value = false
})

const progress = computed(() => {
	if (!monitor.value || monitor.value.status !== 'ACTIVE' || !monitor.value.started_at) return 0
	const total = (monitor.value.duration_minutes + extraMinutes.value) * 60_000
	const elapsed = now.value - new Date(monitor.value.started_at).getTime()
	return Math.min(100, Math.max(0, (elapsed / total) * 100))
})

async function run(action: () => Promise<unknown>, note = ''): Promise<void> {
	busy.value = true
	error.value = ''
	try {
		await action()
		await poll()
		emit('changed')
		if (note) toast(note)
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err)
	} finally {
		busy.value = false
	}
}

// after ending a round, the obvious next step is offered directly instead of
// hiding behind the round dropdown
/** Round statuses as the SERVER currently has them.
 *
 * props.assembly is refreshed only when something emits 'changed', so these
 * used to be computed from a snapshot taken on mount: the card could offer to
 * start a round that was already running, or hide one that was available. The
 * monitor poll now carries every round's status, so the same request that says
 * "8/8 connected" also says which rounds exist and where they are.
 */
const liveRounds = computed(() => monitor.value?.rounds ?? props.assembly.rounds)

const nextUp = computed(() => {
	if (!monitor.value) return null
	// a closed assembly is over: offering "Start Round N" here is what pushed
	// every phone into the next round after the organizer ended things early
	if (props.assembly.closed_at) return null
	if (!['ENDED', 'PROCESSING', 'READY_FOR_REVIEW'].includes(monitor.value.status)) return null
	const rounds = liveRounds.value
	const index = rounds.findIndex((r) => r.id === roundId.value)
	if (index < 0) return null
	return rounds.slice(index + 1).find((r) => r.status === 'NOT_STARTED') ?? null
})

const allRoundsDone = computed(
	() =>
		!!monitor.value &&
		['ENDED', 'PROCESSING', 'READY_FOR_REVIEW'].includes(monitor.value.status) &&
		liveRounds.value.length > 0 &&
		liveRounds.value.every((r) => r.status !== 'NOT_STARTED' && r.status !== 'ACTIVE'),
)

async function startNextRound(): Promise<void> {
	if (!nextUp.value) return
	roundId.value = nextUp.value.id
	await poll()
	startRound()
}

function startRound(): void {
	// orchestrated: warn (never block) when tables haven't armed yet
	if (
		monitor.value &&
		monitor.value.recording_mode !== 'independent' &&
		monitor.value.tables_ready < monitor.value.tables_total &&
		!confirmStartUnready.value
	) {
		confirmStartUnready.value = true
		return
	}
	confirmStartUnready.value = false
	void run(() => api.startRound(roundId.value), 'Round started — armed tables are now recording')
}

const endRound = () => run(() => api.endRound(roundId.value), 'Round ended')

async function showTranscript(recordingId: string): Promise<void> {
	if (transcriptFor.value === recordingId) {
		transcriptFor.value = ''
		transcript.value = null
		return
	}
	transcriptFor.value = recordingId
	transcript.value = null
	transcriptError.value = ''
	try {
		transcript.value = await api.getTranscript(recordingId)
	} catch (err) {
		transcriptError.value = err instanceof Error ? err.message : String(err)
	}
}

const transcribe = (recordingId: string) =>
	run(() => api.requestTranscription(recordingId), 'Transcription queued')

async function showDevice(tableNumber: number): Promise<void> {
	openTable.value = openTable.value === tableNumber ? null : tableNumber
	deviceLog.value = []
	if (openTable.value !== null) {
		try {
			const logs = await api.deviceLogs(props.assembly.id, tableNumber, 50)
			deviceLog.value = logs.lines
		} catch {
			deviceLog.value = []
		}
	}
}

function speakerClass(speaker: string): string {
	const match = speaker.match(/(\d+)/)
	if (!match) return ''
	return `cz-convo__seg--s${((parseInt(match[1], 10) - 1) % 5) + 1}`
}

/* ---- exception-first: healthy tables collapse, problems stay in view ----
 *
 * Fifty green rows tell a facilitator nothing; the two that need a hand are
 * what the screen is for. The server's readiness judgement (0.7) decides: a
 * READY table with nothing the client itself flags is "quiet" and folds into
 * one row, anything else stays expanded with its reasons worded here and the
 * fix beside it. A server without readiness (older) collapses nothing. */

const REASON_TEXT: Record<string, string> = {
	NO_RECORDER: 'no phone has joined — show the table its QR code',
	RECORDER_OFFLINE: 'phone not answering',
	MIC_UNAVAILABLE: 'microphone not capturing — tap the phone to allow it',
	LOW_STORAGE: 'storage low — swap or free the phone after this session',
	LOW_BATTERY: 'battery low — ask the table for a backup phone',
	UPLOAD_STALLED: 'upload backlog — check the venue Wi-Fi',
	LIVE_STT_UNAVAILABLE: 'live captions off at this table',
	HELP_REQUESTED: 'the table asks for help',
	PARTICIPANT_CONSENT_MISSING: 'nobody at the table has consented yet — register a participant on the table phone',
}

/** What a table's raised hand is about, in the organizer's words. */
const HELP_KIND_TEXT: Record<string, string> = {
	TECHNICAL: 'technical problem',
	ORGANIZER: 'wants the organizer',
	PROCESS: 'question about the process',
}

function reasonText(reason: { code: string; slot: number | null; data: Record<string, unknown> }): string {
	if (reason.code === 'HELP_REQUESTED') {
		const kind = HELP_KIND_TEXT[String(reason.data.kind)] ?? String(reason.data.kind ?? '').toLowerCase()
		return `${REASON_TEXT.HELP_REQUESTED}${kind ? ` — ${kind}` : ''}`
	}
	const base = REASON_TEXT[reason.code] ?? reason.code.toLowerCase().replaceAll('_', ' ')
	const who = reason.slot !== null && reason.slot !== undefined && (reason.slot > 1 || reason.code !== 'NO_RECORDER')
		? ` (recorder ${String.fromCharCode(64 + reason.slot)})`
		: ''
	return base + who
}

/** Nothing the server or this screen would point at. */
function isQuiet(table: MonitorTable): boolean {
	if (!table.readiness || table.readiness.status !== 'READY') return false
	return !(
		captureInterrupted(table) ||
		lowBattery(table) ||
		lowStorage(table) ||
		canReplaceDevice(table) ||
		canRetryAssembly(table) ||
		table.superseded_recordings.length > 0
	)
}

const showQuiet = ref(false)

/* ---- advanced diagnostics: the numbers behind a pill, on demand ----
 * Battery, storage, upload backlog, heartbeat age, wake lock, capture — every
 * recorder's heartbeat already arrives in the monitor payload; the normal view
 * words it, this shows it. A per-browser toggle, off by default. */
const ADVANCED_KEY = 'citizens-live-advanced'
const advanced = ref(false)
try {
	advanced.value = localStorage.getItem(ADVANCED_KEY) === '1'
} catch {
	/* private mode */
}
function toggleAdvanced(): void {
	advanced.value = !advanced.value
	try {
		localStorage.setItem(ADVANCED_KEY, advanced.value ? '1' : '0')
	} catch {
		/* ignore */
	}
}

type RecorderEntry = NonNullable<MonitorTable['recorders']>[number]

/** One line of facts per recorder, dashes where the phone said nothing. */
function recorderFacts(recorder: RecorderEntry): string {
	const s = recorder.status ?? {}
	const pct = typeof s.battery_level === 'number' ? `${Math.round(s.battery_level * 100)}%` : '—'
	const storage = typeof s.storage_free_mb === 'number' ? `${Math.round(s.storage_free_mb)} MB free` : '—'
	const pending =
		typeof s.local_chunks === 'number' && typeof s.acked_chunks === 'number'
			? `${Math.max(0, s.local_chunks - s.acked_chunks)} chunks pending`
			: '—'
	const age = recorder.seconds_since_contact === null ? 'never heard' : `heartbeat ${recorder.seconds_since_contact}s ago`
	const screen = s.screen_awake === true ? 'screen awake' : s.screen_awake === false ? 'screen may lock' : '—'
	const visible = s.visible === false ? 'in background' : s.visible === true ? 'foreground' : '—'
	const capture = s.capture_ok === false ? 'capture interrupted' : s.capture_ok === true ? 'capturing' : '—'
	const rec = recorder.recording ? recorder.recording.state : 'no recording'
	return `battery ${pct} · ${storage} · ${pending} · ${age} · ${screen} · ${visible} · ${capture} · ${rec}`
}
const quietTables = computed(() => (monitor.value?.tables ?? []).filter(isQuiet))
const attentionTables = computed(() => (monitor.value?.tables ?? []).filter((t) => !isQuiet(t)))
const visibleTables = computed(() =>
	showQuiet.value ? (monitor.value?.tables ?? []) : attentionTables.value,
)

/** The one line at the top: all fine, or how many need a hand. */
const health = computed(() => {
	const m = monitor.value
	if (!m?.readiness || !m.tables.length) return null
	const attention = attentionTables.value.length
	const blocked = m.tables.filter((t) => t.readiness?.status === 'BLOCKED').length
	if (attention === 0) return { tone: 'ok', text: 'Everything is running normally.' }
	const noun = attention === 1 ? 'table needs' : 'tables need'
	return {
		tone: blocked ? 'bad' : 'warn',
		text: `${attention} ${noun} attention${blocked ? ` · ${blocked} cannot record` : ''}.`,
	}
})

function deviceState(table: MonitorTable): { status: string; label: string } {
	if (table.armed) return { status: 'CONNECTED', label: 'armed' }
	// the page is alive but not on screen: iOS can stop the microphone in
	// that state with no error the page can catch, so it is not "connected"
	if (table.device.connected && table.device.status.visible === false)
		return { status: 'STALE', label: 'in background' }
	if (table.device.connected) return { status: 'CONNECTED', label: 'connected' }
	if (table.device.seconds_since_contact !== null)
		return { status: 'STALE', label: relativeAge(table.device.seconds_since_contact) }
	return { status: 'IDLE', label: 'no device' }
}

/** Roughly twenty minutes of audio left, at the recorder's bitrate. Enough
 * warning to finish the round and swap the phone between rounds. */
const LOW_STORAGE_MB = 200

/** Enough charge to finish a round, not enough to start another. The point of
 * showing it at all is to swap a phone BEFORE it dies, rather than recovering
 * afterwards. Only Chromium reports battery, so a table showing nothing here
 * is unknown, not healthy — never present its absence as reassurance. */
const LOW_BATTERY = 0.15

/** States in which a table is still expected to be sending audio. */
const LIVE_RECORDING_STATES = ['RECORDING', 'FINALIZING', 'WAITING_FOR_CHUNKS']

/** The phone says it is recording but no audio has come out of the
 * microphone for half a minute. Only a recent heartbeat counts: a stale one
 * is the STALE pill's business, and older recorder builds never send the
 * field at all. */
function captureInterrupted(table: MonitorTable): boolean {
	const status = table.device.status
	return table.device.connected && status.recording_active === true && status.capture_ok === false
}

const confirmReplace = ref<MonitorTable | null>(null)

/** Offer to hand this table to another phone.
 *
 * Only when the device has stopped answering (the server's 45 s threshold) AND
 * a recording is still open — otherwise this is a healthy table and replacing
 * its device is not a thing anyone should be invited to do.
 */
function canReplaceDevice(table: MonitorTable): boolean {
	if (table.device.connected || !table.recording) return false
	return LIVE_RECORDING_STATES.includes(table.recording.state)
}

/** Audio the server holds for a phone that is gone, not yet assembled.
 *
 * Once the sweep has given up on the phone the recording is UPLOAD_INCOMPLETE,
 * where Replace device no longer applies — and the only way to turn the audio
 * into a transcript was a Retry button on the Files tab that nothing on this
 * screen pointed at. The sweep now assembles it by itself after half an hour;
 * this is for the facilitator who does not want to wait.
 */
function canRetryAssembly(table: MonitorTable): boolean {
	const recording = table.recording
	if (!recording) return false
	return (
		(recording.state === 'UPLOAD_INCOMPLETE' && recording.received_chunks > 0) ||
		recording.state === 'AUDIO_INVALID'
	)
}

async function retryAssembly(table: MonitorTable): Promise<void> {
	const recording = table.recording
	if (!recording) return
	await run(
		() => api.retryAssembly(recording.id),
		`Table ${table.number}: assembling the audio that reached the server`,
	)
}

/** What the earlier recording of a table is, in the room's words — never the
 * engine's ("superseded", "replacement"). It is an earlier part of the same
 * discussion; the suffix says why the phone changed. */
function priorLabel(prior: { error_code: string }): string {
	switch (prior.error_code) {
		case 'ROUND_CONTINUED':
			return 'earlier part — the table continued'
		case 'DEVICE_REJOINED':
			return 'earlier part — the phone reconnected'
		case 'DEVICE_SILENT':
			return 'earlier part — the phone went silent'
		default:
			return 'earlier part — the phone was handed over'
	}
}

async function replaceDevice(): Promise<void> {
	const table = confirmReplace.value
	confirmReplace.value = null
	if (!table?.recording) return
	busy.value = true
	try {
		const result = await api.replaceDevice(table.recording.id)
		toast(
			result.assembling
				? `Table ${table.number} released — its recording so far is being transcribed`
				: `Table ${table.number} released — it had not uploaded any audio yet`,
		)
		await polling.refresh()
		emit('changed')
	} catch (err) {
		error.value = describeError(err).message
	} finally {
		busy.value = false
	}
}

function lowBattery(table: MonitorTable): boolean {
	const level = table.device.status.battery_level
	return typeof level === 'number' && level < LOW_BATTERY
}

function lowStorage(table: MonitorTable): boolean {
	const free = table.device.status.storage_free_mb
	return typeof free === 'number' && free < LOW_STORAGE_MB
}

function pendingChunks(table: MonitorTable): number {
	return (table.device.status.local_chunks ?? 0) - (table.device.status.acked_chunks ?? 0)
}
</script>

<template>
	<div :class="{ 'cz-stale': polling.consecutiveFailures.value > 0 }">
		<div class="cz-row cz-row--spread" style="margin-bottom: 10px">
			<CzFreshness
				:last-success-at="polling.lastSuccessAt.value"
				:consecutive-failures="polling.consecutiveFailures.value"
				@refresh="polling.refresh()" />
		</div>

		<div v-if="error" class="cz-error">{{ error }}</div>

		<div
			v-if="nextUp && monitor?.recording_mode !== 'independent'"
			class="cz-card cz-nextstep">
			<div>
				<strong>This round has finished.</strong>
				<span class="cz-muted" style="display: block; font-size: 0.8125rem; margin-top: 2px">
					Armed tables will start recording Session {{ nextUp.position }} automatically.
				</span>
			</div>
			<CzButton variant="primary" :icon="mdiPlay" :disabled="busy" @click="startNextRound">
				Start Session {{ nextUp.position }}{{ nextUp.title ? ` — ${nextUp.title}` : '' }}
			</CzButton>
		</div>

		<div
			v-else-if="allRoundsDone"
			class="cz-card cz-nextstep">
			<div>
				<strong>All sessions are done.</strong>
				<span class="cz-muted" style="display: block; font-size: 0.8125rem; margin-top: 2px">
					Review the findings in the Analysis tab, then publish the report to the
					table phones from the Report tab.
				</span>
			</div>
		</div>

		<!-- exception-first: the state of the room in one line -->
		<div v-if="health" class="cz-health" :class="`cz-health--${health.tone}`" role="status">
			<strong>{{ health.text }}</strong>
			<span v-if="quietTables.length && attentionTables.length" class="cz-muted">
				{{ quietTables.length }} {{ quietTables.length === 1 ? 'table is' : 'tables are' }} fine and folded below.
			</span>
			<span style="margin-left: auto">
				<CzButton variant="tertiary" small data-test="advanced" @click="toggleAdvanced">
					{{ advanced ? 'Hide diagnostics' : 'Advanced diagnostics' }}
				</CzButton>
			</span>
		</div>

		<!-- the facilitator's voice to the tables -->
		<div v-if="monitor && monitor.status === 'ACTIVE'" class="cz-broadcast">
			<div class="cz-broadcast__row">
				<strong>Message the tables</strong>
				<CzButton variant="secondary" small :disabled="messageBusy" @click="sendMessage({ kind: 'TIME_LEFT', minutes: 10 })">
					10 min left
				</CzButton>
				<CzButton variant="secondary" small :disabled="messageBusy" @click="sendMessage({ kind: 'TIME_LEFT', minutes: 5 })">
					5 min left
				</CzButton>
				<CzButton variant="secondary" small :disabled="messageBusy" @click="sendMessage({ kind: 'TIME_LEFT', minutes: 1 })">
					1 min left
				</CzButton>
				<CzButton variant="secondary" small :disabled="messageBusy" @click="sendMessage({ kind: 'WRAP_UP', sound: true })">
					Wrap up
				</CzButton>
				<CzButton variant="tertiary" small @click="messagesOpen = !messagesOpen">
					{{ messagesOpen ? 'Less' : 'Write a message' }}
				</CzButton>
				<label class="cz-broadcast__target">
					to
					<select v-model="messageTarget">
						<option :value="null">all tables</option>
						<option v-for="table in monitor.tables" :key="table.number" :value="table.number">
							Table {{ table.number }}
						</option>
					</select>
				</label>
			</div>
			<form v-if="messagesOpen" class="cz-broadcast__row" @submit.prevent="sendCustom">
				<input
					v-model="messageText"
					type="text"
					maxlength="300"
					placeholder="A prompt or an instruction for the tables"
					aria-label="Message to the tables"
					style="flex: 1; min-width: 220px" />
				<CzButton variant="primary" small type="submit" :disabled="messageBusy || !messageText.trim()">
					Send
				</CzButton>
			</form>
			<ul v-if="recentMessages.length" class="cz-broadcast__log">
				<li v-for="message in recentMessages" :key="message.id">
					<span class="cz-muted">{{ clockOf(message.created_at) }}</span>
					<span v-if="message.target_table_number" class="cz-muted"> · Table {{ message.target_table_number }}</span>
					— {{ message.text }}
					<span class="cz-broadcast__delivery" :class="{ 'cz-broadcast__delivery--partial': message.not_seen_by.length }">
						{{ deliveryText(message) }}
					</span>
				</li>
			</ul>
		</div>

		<div class="cz-countbar">
			<select v-model="roundId" style="min-width: 200px">
				<option v-for="round in assembly.rounds" :key="round.id" :value="round.id">
					{{ roundHeading(round.position, round.title) }}
				</option>
			</select>
			<template v-if="monitor">
				<CzStatusPill :status="monitor.status" />
				<span
					v-if="monitor.recording_mode !== 'independent'"
					class="cz-pill"
					:class="monitor.tables_ready === monitor.tables_total ? 'cz-pill--green' : 'cz-pill--amber'"
					style="text-transform: none">
					{{ monitor.tables_ready }}/{{ monitor.tables_total }} tables ready
				</span>
				<div class="cz-countbar__track">
					<div class="cz-countbar__fill" :style="{ width: progress + '%' }"></div>
				</div>
				<span
					v-if="remaining"
					class="cz-countbar__time"
					:class="{ 'cz-drifted': overrunning }">
					{{ remaining }}
				</span>
				<template v-if="monitor.recording_mode !== 'independent'">
					<!-- time is up: end it on time, but let the facilitator take the
					     exception. Cutting a table off mid-sentence at a civic
					     assembly is worse than a round running a minute long. -->
					<template v-if="autoEndIn !== null">
						<span class="cz-drifted" style="font-size: 0.8125rem" role="status">
							Time is up — ending in {{ autoEndIn }}s
						</span>
						<CzButton variant="secondary" :disabled="busy" @click="extendRound">
							Extend {{ EXTEND_MINUTES }} min
						</CzButton>
						<CzButton variant="tertiary" :disabled="busy" @click="autoEndCancelled = true">
							Keep going
						</CzButton>
					</template>
					<CzButton
						v-if="monitor.status === 'NOT_STARTED' || monitor.status === 'ENDED'"
						variant="primary"
						:icon="mdiPlay"
						:disabled="busy"
						@click="startRound">
						Start session
					</CzButton>
					<CzButton
						v-else-if="monitor.status === 'ACTIVE'"
						variant="danger"
						:icon="mdiStop"
						:disabled="busy"
						@click="endRound">
						End session
					</CzButton>
				</template>
				<span v-else class="cz-muted" style="font-size: 0.8125rem">
					Independent tables — each table records on its own schedule
				</span>
			</template>
		</div>

		<CzConfirm
			v-if="confirmReplace"
			title="Hand this table to another phone?"
			:message="`Table ${confirmReplace.number}'s phone has stopped responding. Its recording is finished with the audio already received — usually most of the session — and transcribed. The table can then record the rest on any phone by scanning the same QR code.`"
			confirm-label="Hand over the table"
			tone="danger"
			@confirm="replaceDevice"
			@cancel="confirmReplace = null" />

		<CzConfirm
			v-if="confirmStartUnready && monitor"
			title="Start with tables missing?"
			:message="`Only ${monitor.tables_ready} of ${monitor.tables_total} tables are armed and ready. Tables that arm later can still join the round. Start anyway?`"
			confirm-label="Start session"
			@confirm="startRound"
			@cancel="confirmStartUnready = false" />

		<CzEmptyState
			v-if="!roundId"
			:icon="mdiClipboardTextOutline"
			title="This assembly has no sessions yet"
			hint="Add a session on the Sessions tab to start recording." />

		<CzSkeleton v-else-if="!monitor" :rows="5" />

		<template v-else>
			<table class="cz-table">
				<thead>
					<tr>
						<th>Table</th><th>Device</th><th>Recording</th><th>Elapsed</th><th>Upload</th><th>Local audio</th><th style="text-align: right">Actions</th>
					</tr>
				</thead>
				<tbody>
					<!-- healthy tables fold into one row; the ones needing a hand stay -->
					<tr v-if="quietTables.length" class="cz-quietrow">
						<td colspan="7">
							<CzButton variant="tertiary" small @click="showQuiet = !showQuiet">
								{{ quietTables.length }} {{ quietTables.length === 1 ? 'table' : 'tables' }} running normally —
								{{ showQuiet ? 'hide' : 'show' }}
							</CzButton>
						</td>
					</tr>
					<tr
						v-for="table in visibleTables"
						:key="table.table_id"
						:class="{ 'cz-row--quiet': isQuiet(table) }">
						<td>
							<span class="cz-posbadge">{{ table.number }}</span>
							<!-- a table with more than one recorder phone: say so, and
							     which of them are reachable -->
							<div
								v-if="(table.recorders?.length ?? 0) > 1"
								class="cz-muted"
								style="font-size: 0.78rem; margin-top: 4px; white-space: nowrap">
								{{ table.recorders!.length }} recorders ·
								{{ table.recorders!.filter((r) => r.connected).map((r) => r.label).join(', ') || 'none' }} connected
							</div>
							<!-- advanced: the heartbeat facts behind the pills, per recorder -->
							<ul v-if="advanced && table.recorders?.length" class="cz-diag" data-test="diagnostics">
								<li v-for="recorder in table.recorders" :key="recorder.slot">
									<strong>{{ recorder.label }}</strong> {{ recorderFacts(recorder) }}
								</li>
							</ul>
							<!-- the server's reasons, worded, with the fix in the row's
							     Actions column rather than on a settings page -->
							<ul v-if="table.readiness && table.readiness.reasons.length" class="cz-reasons">
								<li
									v-for="reason in table.readiness.reasons"
									:key="reason.code + (reason.slot ?? '')"
									:class="reason.severity === 'blocker' ? 'cz-reasons__blocker' : 'cz-reasons__warning'">
									{{ reasonText(reason) }}
								</li>
							</ul>
						</td>
						<td><CzStatusPill :status="deviceState(table).status" :label="deviceState(table).label" /></td>
						<td>
							<CzStatusPill v-if="table.recording" :status="table.recording.state" />
							<!-- the server already returns error_code; the Live tab was the
							     one place a failure showed as a bare pill with no reason -->
							<CzFailureNote
								v-if="table.recording"
								:state="table.recording.state"
								:error-code="table.recording.error_code"
								:job="table.recording.job" />
							<span v-else class="cz-muted">—</span>
							<!-- the half a replaced phone left behind: still finishing
							     its transcript, and it used to vanish from here the
							     instant the replacement started -->
							<div
								v-for="prior in table.superseded_recordings"
								:key="prior.id"
								class="cz-muted"
								style="font-size: 0.78rem; margin-top: 4px">
								<CzStatusPill :status="prior.state" />
								<CzFailureNote :state="prior.state" :error-code="prior.error_code" :job="prior.job" />
								<span>({{ priorLabel(prior) }})</span>
							</div>
						</td>
						<td>
							<!-- rounds start at different times because each table is
							     started by hand, so tables end at different times too.
							     Participants reported this as unfair and confusing; the
							     facilitator could not see the drift at all. -->
							<span
								v-if="tableElapsed(table)"
								style="font-variant-numeric: tabular-nums"
								:class="{ 'cz-drifted': tableDrift(table) > DRIFT_WARNING_S }">
								{{ tableElapsed(table) }}
							</span>
							<span v-else class="cz-muted">—</span>
						</td>
						<td>
							<template v-if="table.device.status.local_chunks !== undefined">
								<span style="font-variant-numeric: tabular-nums">
									{{ table.device.status.acked_chunks }}/{{ table.device.status.local_chunks }}
								</span>
								<span v-if="pendingChunks(table) > 3" style="color: var(--cz-amber); font-weight: 600">
									({{ pendingChunks(table) }} pending)
								</span>
							</template>
							<span v-else-if="table.recording" style="font-variant-numeric: tabular-nums">
								{{ table.recording.received_chunks }} received
							</span>
							<span v-else class="cz-muted">—</span>
						</td>
						<td>
							<!-- The phone reports free space on every heartbeat, but this
							     only ever rendered once storage_ok went false — i.e. after
							     it had already failed. A table about to run out mid-round
							     is exactly what an organizer can still act on. -->
							<!-- The microphone went quiet mid-round (screen off on an
							     iPhone, a call) and the phone is trying to get it back.
							     Red, ahead of everything: nothing is being recorded at
							     that table right now, and a tap on the phone fixes it. -->
							<CzStatusPill
								v-if="captureInterrupted(table)"
								status="STALLED"
								label="capture interrupted" />
							<CzStatusPill
								v-else-if="table.device.status.storage_ok === false"
								status="OFFLINE"
								label="storage error" />
							<!-- No wake lock: the screen will switch off at the phone's own
							     timeout unless auto-lock is set to Never by hand. -->
							<CzStatusPill
								v-else-if="table.device.connected && table.device.status.screen_awake === false"
								status="PROCESSING"
								label="screen may lock" />
							<CzStatusPill
								v-else-if="lowBattery(table)"
								status="PROCESSING"
								:label="`battery ${Math.round((table.device.status.battery_level ?? 0) * 100)}%`" />
							<CzStatusPill
								v-else-if="lowStorage(table)"
								status="PROCESSING"
								:label="`low storage — ${Math.round(table.device.status.storage_free_mb ?? 0)} MB`" />
							<CzStatusPill v-else-if="table.local_recording_safe" status="SAFE" label="✓ safe" />
							<span v-else class="cz-muted">unknown</span>
						</td>
						<td style="text-align: right">
							<div class="cz-row" style="gap: 4px; justify-content: flex-end; flex-wrap: nowrap">
								<CzButton
									v-if="table.recording && ['AUDIO_READY', 'TRANSCRIPTION_FAILED', 'TRANSCRIBING'].includes(table.recording.state)"
									small
									variant="primary"
									:icon="mdiTextBoxPlusOutline"
									:disabled="busy"
									:title="table.recording.state === 'TRANSCRIBING' ? 'Retry transcription (use if it has been stuck)' : 'Transcribe'"
									@click="transcribe(table.recording.id)" />
								<CzButton
									v-if="table.recording && table.recording.state === 'TRANSCRIBED'"
									small
									:variant="transcriptFor === table.recording.id ? 'primary' : 'secondary'"
									:icon="mdiTextBoxOutline"
									title="Transcript"
									@click="showTranscript(table.recording.id)" />
								<CzButton
									v-if="table.help_request"
									small
									variant="primary"
									:icon="mdiHandBackLeft"
									title="The table raised its hand — tell it you have seen it"
									:disabled="busy"
									@click="acknowledgeHelp(table)">
									Acknowledge
								</CzButton>
								<CzButton
									v-if="canReplaceDevice(table)"
									small
									variant="danger"
									:icon="mdiCellphoneRemove"
									title="This table's phone has stopped responding — hand the table to another phone"
									:disabled="busy"
									@click="confirmReplace = table">
									Hand over table
								</CzButton>
								<CzButton
									v-if="canRetryAssembly(table)"
									small
									variant="secondary"
									:icon="mdiRefresh"
									title="Assemble and transcribe the audio that reached the server before the phone stopped"
									:disabled="busy"
									@click="retryAssembly(table)">
									Retry
								</CzButton>
								<CzButton
									small
									variant="tertiary"
									:icon="mdiConsoleLine"
									title="Device log"
									@click="showDevice(table.number)" />
							</div>
						</td>
					</tr>
				</tbody>
			</table>

			<p v-if="monitor.tables.length === 0" class="cz-muted" style="margin-top: 14px">
				<SvgIcon :path="mdiMonitorEye" :size="16" /> This round has no tables.
			</p>

			<div v-if="transcriptFor" class="cz-card" style="margin-top: 16px">
				<div class="cz-row cz-row--spread" style="margin-bottom: 8px">
					<h3>Transcript</h3>
					<span v-if="transcript" class="cz-muted" style="font-size: 0.78rem">
						{{ transcript.provider }} · {{ transcript.model }} · {{ transcript.language.toUpperCase() }}
					</span>
				</div>
				<div v-if="transcriptError" class="cz-error">{{ transcriptError }}</div>
				<CzSkeleton v-else-if="!transcript" :rows="3" :height="36" />
				<template v-else>
					<p v-if="transcript.segments.length === 0" class="cz-muted">
						The transcript is empty (no speech detected).
					</p>
					<div v-else class="cz-convo">
						<div
							v-for="segment in transcript.segments"
							:key="segment.id"
							class="cz-convo__seg"
							:class="speakerClass(segment.speaker)">
							<span class="cz-convo__time">{{ timestamp(segment.start) }}</span>
							<div class="cz-convo__body">
								<span v-if="segment.speaker" class="cz-convo__speaker">{{ segment.speaker }}</span>
								<p class="cz-convo__text">{{ segment.text }}</p>
							</div>
						</div>
					</div>
				</template>
			</div>

			<div v-if="openTable !== null" class="cz-card" style="margin-top: 16px">
				<h3 style="margin-bottom: 10px">Table {{ openTable }} — device log (latest 50)</h3>
				<p v-if="deviceLog.length === 0" class="cz-muted">No device log received yet.</p>
				<div v-else class="cz-logpanel">{{ deviceLog.join('\n') }}</div>
			</div>
		</template>
	</div>
</template>
