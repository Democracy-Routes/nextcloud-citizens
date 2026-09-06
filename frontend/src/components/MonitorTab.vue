<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import { roundHeading } from '../labels'
import {
	mdiCellphoneRemove,
	mdiClipboardTextOutline,
	mdiConsoleLine,
	mdiMonitorEye,
	mdiPlay,
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
import type { AssemblyDetail, MonitorTable, RoundMonitor, TranscriptData } from '../types'
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
}

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
	if (monitor.value?.recording_mode !== 'orchestrated') return
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
	toast(`Round extended by ${EXTEND_MINUTES} minutes`)
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
		monitor.value?.recording_mode === 'orchestrated' &&
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

function deviceState(table: MonitorTable): { status: string; label: string } {
	if (table.armed) return { status: 'CONNECTED', label: 'armed' }
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
			v-if="nextUp && monitor?.recording_mode === 'orchestrated'"
			class="cz-card cz-nextstep">
			<div>
				<strong>This round has finished.</strong>
				<span class="cz-muted" style="display: block; font-size: 0.8125rem; margin-top: 2px">
					Armed tables will start recording Round {{ nextUp.position }} automatically.
				</span>
			</div>
			<CzButton variant="primary" :icon="mdiPlay" :disabled="busy" @click="startNextRound">
				Start Round {{ nextUp.position }}{{ nextUp.title ? ` — ${nextUp.title}` : '' }}
			</CzButton>
		</div>

		<div
			v-else-if="allRoundsDone"
			class="cz-card cz-nextstep">
			<div>
				<strong>All rounds are done.</strong>
				<span class="cz-muted" style="display: block; font-size: 0.8125rem; margin-top: 2px">
					Review the findings in the Analysis tab, then publish the report to the
					table phones from the Report tab.
				</span>
			</div>
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
					v-if="monitor.recording_mode === 'orchestrated'"
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
				<template v-if="monitor.recording_mode === 'orchestrated'">
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
						Start round
					</CzButton>
					<CzButton
						v-else-if="monitor.status === 'ACTIVE'"
						variant="danger"
						:icon="mdiStop"
						:disabled="busy"
						@click="endRound">
						End round
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
			:message="`Table ${confirmReplace.number}'s phone has stopped responding. Its recording is finished with the audio already received — usually most of the round — and transcribed. The table can then record the rest on any phone by scanning the same QR code.`"
			confirm-label="Replace device"
			tone="danger"
			@confirm="replaceDevice"
			@cancel="confirmReplace = null" />

		<CzConfirm
			v-if="confirmStartUnready && monitor"
			title="Start with tables missing?"
			:message="`Only ${monitor.tables_ready} of ${monitor.tables_total} tables are armed and ready. Tables that arm later can still join the round. Start anyway?`"
			confirm-label="Start round"
			@confirm="startRound"
			@cancel="confirmStartUnready = false" />

		<CzEmptyState
			v-if="!roundId"
			:icon="mdiClipboardTextOutline"
			title="This assembly has no rounds yet"
			hint="Add a round on the Rounds tab to start recording." />

		<CzSkeleton v-else-if="!monitor" :rows="5" />

		<template v-else>
			<table class="cz-table">
				<thead>
					<tr>
						<th>Table</th><th>Device</th><th>Recording</th><th>Elapsed</th><th>Upload</th><th>Local audio</th><th style="text-align: right">Actions</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="table in monitor.tables" :key="table.table_id">
						<td><span class="cz-posbadge">{{ table.number }}</span></td>
						<td><CzStatusPill :status="deviceState(table).status" :label="deviceState(table).label" /></td>
						<td>
							<CzStatusPill v-if="table.recording" :status="table.recording.state" />
							<!-- the server already returns error_code; the Live tab was the
							     one place a failure showed as a bare pill with no reason -->
							<CzFailureNote
								v-if="table.recording"
								:state="table.recording.state"
								:error-code="table.recording.error_code" />
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
								<CzFailureNote :state="prior.state" :error-code="prior.error_code" />
								<span>(replaced device)</span>
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
							<CzStatusPill
								v-if="table.device.status.storage_ok === false"
								status="OFFLINE"
								label="storage error" />
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
									v-if="canReplaceDevice(table)"
									small
									variant="danger"
									:icon="mdiCellphoneRemove"
									title="This table's phone has stopped responding — hand the table to another device"
									:disabled="busy"
									@click="confirmReplace = table">
									Replace device
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
