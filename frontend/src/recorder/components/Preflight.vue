<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import {
	mdiAlert,
	mdiCheckCircle,
	mdiCloseCircle,
	mdiDatabaseOutline,
	mdiHarddisk,
	mdiMicrophoneOutline,
	mdiPlay,
	mdiRecordCircleOutline,
	mdiServerNetwork,
	mdiWaveform,
} from '@mdi/js'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import SvgIcon from '../../components/ui/SvgIcon.vue'
import { recorderApi, type JoinResult, type RoundInfo } from '../api'
import { useWakeLock } from '../useWakeLock'
import { pickMimeType } from '../engine'
import { idb } from '../idb'

const props = defineProps<{ session: JoinResult }>()
const emit = defineEmits<{ ready: []; start: [round: RoundInfo]; report: [] }>()

const { t } = useI18n()

// independent tables pick a round and start right here — one screen, one tap;
// orchestrated tables arm with READY and the facilitator starts the round
const orchestrated = props.session.assembly.recording_mode === 'orchestrated'

const openRounds = computed(() => props.session.rounds.filter((r) => !r.recorded_state))
const selectedRound = ref<RoundInfo | null>(
	props.session.rounds.filter((r) => !r.recorded_state).find((r) => r.status === 'ACTIVE') ??
		props.session.rounds.filter((r) => !r.recorded_state)[0] ??
		null,
)
const reportAvailable = ref(false)
const tableSummaries = ref<Array<{ position: number; summary: string }>>([])

let reportTimer = 0

// once this table is finished, watch for the report becoming available and
// for this table's own AI summaries landing
async function pollReport(): Promise<void> {
	try {
		const status = await recorderApi.status(props.session.session_token)
		reportAvailable.value = status.report_available ?? false
		tableSummaries.value = status.rounds
			.filter((r) => r.recorded_state)
			.map((r) => ({ position: r.position, summary: r.table_summary ?? '' }))
	} catch {
		/* offline */
	}
}

type CheckState = 'pending' | 'ok' | 'warn' | 'fail'

const checks = ref<Record<string, { state: CheckState; note: string }>>({
	microphone: { state: 'pending', note: '' },
	recorder: { state: 'pending', note: '' },
	storage: { state: 'pending', note: '' },
	persistent: { state: 'pending', note: '' },
	server: { state: 'pending', note: '' },
})
const level = ref(0)
const testState = ref<'idle' | 'recording' | 'ready' | 'playing'>('idle')

let stream: MediaStream | null = null
let audioContext: AudioContext | null = null
let levelTimer = 0
let testRecorder: MediaRecorder | null = null
let testBuffer: AudioBuffer | null = null
let testSource: AudioBufferSourceNode | null = null

function set(check: string, state: CheckState, note = ''): void {
	checks.value[check] = { state, note }
}

useWakeLock()

/** Run every readiness check.
 *
 * Extracted from onMounted so the microphone failure is not a dead end: on
 * Android a hard denial is never re-prompted, so "allow it and reload" is
 * advice that does not work. Changing the site setting and re-running the
 * check does.
 */
async function runChecks(): Promise<void> {
	window.clearInterval(levelTimer)
	stream?.getTracks().forEach((track) => track.stop())
	try {
		stream = await navigator.mediaDevices.getUserMedia({ audio: true })
		set('microphone', 'ok')
		audioContext = new AudioContext()
		const source = audioContext.createMediaStreamSource(stream)
		const analyser = audioContext.createAnalyser()
		analyser.fftSize = 512
		source.connect(analyser)
		const samples = new Uint8Array(analyser.fftSize)
		levelTimer = window.setInterval(() => {
			analyser.getByteTimeDomainData(samples)
			let peak = 0
			for (const value of samples) peak = Math.max(peak, Math.abs(value - 128))
			level.value = Math.min(100, Math.round((peak / 128) * 160))
		}, 90)
	} catch {
		set('microphone', 'fail', 'Microphone access denied or unavailable')
	}

	const mime = pickMimeType()
	if (mime) set('recorder', 'ok', mime.split(';')[0])
	else set('recorder', 'fail', 'No supported recording format')

	try {
		await idb.selfTest()
		let note = ''
		if (navigator.storage?.estimate) {
			const { quota, usage } = await navigator.storage.estimate()
			if (quota) note = `${Math.round(((quota - (usage ?? 0)) / 1024 / 1024) * 10) / 10} MB free`
		}
		set('storage', 'ok', note)
	} catch {
		set('storage', 'fail', 'Cannot write to local storage')
	}

	try {
		if (navigator.storage?.persist) {
			const persisted = await navigator.storage.persist()
			set('persistent', persisted ? 'ok' : 'warn', persisted ? '' : 'Browser may evict data under pressure')
		} else {
			set('persistent', 'warn', 'Not supported by this browser')
		}
	} catch {
		set('persistent', 'warn', 'Could not request persistence')
	}

	try {
		await recorderApi.status(props.session.session_token)
		set('server', 'ok')
	} catch {
		set('server', 'warn', 'Server unreachable — recording still works locally')
	}

	if (!orchestrated && openRounds.value.length === 0 && props.session.rounds.length > 0) {
		void pollReport()
		reportTimer = window.setInterval(() => void pollReport(), 20_000)
	}
}

onMounted(runChecks)

onBeforeUnmount(() => {
	window.clearInterval(reportTimer)
	window.clearInterval(levelTimer)
	testSource?.stop()
	stream?.getTracks().forEach((track) => track.stop())
	audioContext?.close()
})

function recordTest(): void {
	if (!stream) return
	const mime = pickMimeType()
	if (!mime) return
	testState.value = 'recording'
	const blobs: Blob[] = []
	testRecorder = new MediaRecorder(stream, { mimeType: mime })
	testRecorder.ondataavailable = (event) => blobs.push(event.data)
	testRecorder.onstop = async () => {
		try {
			const data = await new Blob(blobs, { type: mime }).arrayBuffer()
			if (!audioContext) audioContext = new AudioContext()
			testBuffer = await audioContext.decodeAudioData(data)
			testState.value = 'ready'
		} catch {
			testBuffer = null
			testState.value = 'idle'
		}
	}
	testRecorder.start()
	window.setTimeout(() => testRecorder?.stop(), 5000)
}

function playTest(): void {
	if (!testBuffer || !audioContext) return
	testState.value = 'playing'
	testSource = audioContext.createBufferSource()
	testSource.buffer = testBuffer
	testSource.connect(audioContext.destination)
	testSource.onended = () => (testState.value = 'ready')
	testSource.start()
}

function canProceed(): boolean {
	return checks.value.microphone.state === 'ok' &&
		checks.value.recorder.state === 'ok' &&
		checks.value.storage.state === 'ok'
}

const ROWS: Array<{ key: string; label: string; icon: string }> = [
	{ key: 'microphone', label: 'Microphone', icon: mdiMicrophoneOutline },
	{ key: 'recorder', label: 'Audio recording', icon: mdiRecordCircleOutline },
	{ key: 'storage', label: 'Local storage', icon: mdiDatabaseOutline },
	{ key: 'persistent', label: 'Persistent storage', icon: mdiHarddisk },
	{ key: 'server', label: 'Server connection', icon: mdiServerNetwork },
]

const STATE_ICON: Record<CheckState, string> = {
	pending: '', ok: mdiCheckCircle, warn: mdiAlert, fail: mdiCloseCircle,
}
const STATE_CLASS: Record<CheckState, string> = {
	pending: 'rc-pending', ok: 'rc-ok', warn: 'rc-warn', fail: 'rc-bad',
}
</script>

<template>
	<div class="rc-fill">
		<div class="rc-header">
			<span class="rc-table-badge">TABLE {{ session.table_number }}</span>
		</div>

		<div class="rc-scroll">
		<div class="rc-card">
			<h2>Microphone test</h2>
			<div v-for="row in ROWS" :key="row.key" class="rc-status-row">
				<span class="rc-status-row__label">
					<SvgIcon :path="row.icon" :size="19" style="color: var(--rc-muted)" />
					<span>
						{{ row.label }}
						<span v-if="checks[row.key].note" class="rc-status-row__note">{{ checks[row.key].note }}</span>
					</span>
				</span>
				<span :class="STATE_CLASS[checks[row.key].state]">
					<span v-if="checks[row.key].state === 'pending'" class="rc-spin"></span>
					<SvgIcon v-else :path="STATE_ICON[checks[row.key].state]" :size="20" />
				</span>
			</div>

			<p class="rc-eyebrow" style="margin-top: 16px">
				<SvgIcon :path="mdiWaveform" :size="14" /> {{ t('recorder.preflight.level') }}
			</p>
			<div class="rc-level"><div class="rc-level-fill" :style="{ width: level + '%' }"></div></div>

			<button
				class="rc-btn"
				:disabled="testState === 'recording' || checks.microphone.state !== 'ok'"
				@click="recordTest">
				<SvgIcon :path="mdiRecordCircleOutline" :size="20" />
				{{ testState === 'recording' ? 'Recording 5 seconds…' : 'Record 5-second test' }}
			</button>
			<button
				v-if="testState === 'ready' || testState === 'playing'"
				class="rc-btn"
				:disabled="testState === 'playing'"
				@click="playTest">
				<SvgIcon :path="mdiPlay" :size="20" />
				{{ t('recorder.preflight.listen') }}
			</button>
		</div>

		<div v-if="checks.microphone.state === 'fail'" class="rc-alert">
			<strong>{{ t('recorder.preflight.micRequired') }}</strong>
			<p style="margin: 8px 0 0">{{ t('recorder.preflight.micGuidance') }}</p>
			<button class="rc-btn rc-primary" style="margin-top: 12px" @click="runChecks">
				{{ t('recorder.preflight.micRetry') }}
			</button>
		</div>
		<div v-else-if="checks.storage.state === 'fail'" class="rc-alert">
			{{ t('recorder.preflight.noStorage') }}
		</div>

		<template v-if="!orchestrated">
			<div v-if="selectedRound" class="rc-card">
				<p class="rc-eyebrow" style="margin-bottom: 4px">
					Round {{ selectedRound.position }} of {{ session.rounds.length }} ·
					{{ selectedRound.duration_minutes }} minutes
				</p>
				<p class="rc-question" style="margin: 0">{{ selectedRound.question || selectedRound.title }}</p>
				<div v-if="openRounds.length > 1" style="margin-top: 14px">
					<select
						style="width: 100%; padding: 11px; border-radius: 10px; background: var(--rc-surface-2); color: var(--rc-text); border: 1px solid var(--rc-border); font-size: 16px"
						:value="selectedRound.id"
						@change="selectedRound = session.rounds.find((r) => r.id === ($event.target as HTMLSelectElement).value) ?? selectedRound">
						<option
							v-for="round in session.rounds"
							:key="round.id"
							:value="round.id"
							:disabled="!!round.recorded_state">
							Round {{ round.position }} — {{ round.title || round.question || 'Untitled' }}
							{{ round.recorded_state ? ' ✓ recorded' : '' }}
						</option>
					</select>
				</div>
			</div>
			<div v-else-if="session.rounds.length === 0" class="rc-alert">
				{{ t('recorder.preflight.noRounds') }}
			</div>
			<div v-else class="rc-card">
				<p class="rc-eyebrow rc-center" style="display: block">{{ t('recorder.armed.allRecordedTitle') }}</p>
				<p class="rc-muted rc-center" style="margin: 0">{{ t('recorder.armed.allRecordedBody') }}</p>
				<template v-for="entry in tableSummaries" :key="entry.position">
					<p class="rc-eyebrow" style="margin: 10px 0 2px; color: var(--rc-blue)">
						{{ t('recorder.preflight.roundSummary', { position: entry.position }) }}
					</p>
					<p v-if="entry.summary" style="font-size: 14px; margin: 0">{{ entry.summary }}</p>
					<p v-else class="rc-muted" style="font-size: 13.5px; margin: 0">{{ t('recorder.preflight.analyzing') }}</p>
				</template>
				<button v-if="reportAvailable" class="rc-btn rc-primary" @click="emit('report')">
					{{ t('recorder.armed.viewReport') }}
				</button>
			</div>
		</template>
		</div>

		<div class="rc-actions">
			<button v-if="orchestrated" class="rc-btn rc-primary" :disabled="!canProceed()" @click="emit('ready')">
				READY
			</button>
			<button
				v-else-if="selectedRound"
				class="rc-btn rc-record"
				:disabled="!canProceed()"
				@click="emit('start', selectedRound)">
				<SvgIcon :path="mdiRecordCircleOutline" :size="22" />
				Start recording
			</button>
		</div>
	</div>
</template>
