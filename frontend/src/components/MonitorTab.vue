<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
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

const remaining = computed(() => {
	if (!monitor.value || monitor.value.status !== 'ACTIVE' || !monitor.value.started_at) return ''
	const endAt = new Date(monitor.value.started_at).getTime() + monitor.value.duration_minutes * 60_000
	const seconds = Math.max(0, Math.floor((endAt - now.value) / 1000))
	const minutes = Math.floor(seconds / 60)
	return `${String(minutes).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
})

const progress = computed(() => {
	if (!monitor.value || monitor.value.status !== 'ACTIVE' || !monitor.value.started_at) return 0
	const total = monitor.value.duration_minutes * 60_000
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
					Round {{ round.position }} — {{ round.title || 'Untitled' }}
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
				<span v-if="remaining" class="cz-countbar__time">{{ remaining }}</span>
				<template v-if="monitor.recording_mode === 'orchestrated'">
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
						<th>Table</th><th>Device</th><th>Recording</th><th>Upload</th><th>Local audio</th><th style="text-align: right">Actions</th>
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
