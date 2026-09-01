<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { recorderApi, type JoinResult, type RoundInfo } from '../api'
import { useWakeLock } from '../useWakeLock'

/*
 * Orchestrated mode: the table is ARMED. The phone waits for the facilitator
 * to start a round and then begins recording automatically — the arming tap
 * on READY was the human consent at the table.
 */

const props = defineProps<{
	session: JoinResult
	/** a round whose microphone just failed: auto-start must not re-enter it,
	 * or the table is stuck in a five-second failure loop with no way out */
	blockedRoundId?: string | null
}>()
const emit = defineEmits<{ start: [round: RoundInfo]; back: []; report: [] }>()

const rounds = ref<RoundInfo[]>(props.session.rounds)
const offline = ref(false)
const reportAvailable = ref(false)

const { t } = useI18n()

const blockedRound = ref<RoundInfo | null>(null)

/** The table asked to try the microphone again: drop the latch and go. */
function retryBlockedRound(): void {
	const round = blockedRound.value
	if (!round) return
	blockedRound.value = null
	emit('start', round)
}

let pollTimer = 0
let heartbeatTimer = 0

const nextRound = computed(() => rounds.value.find((r) => !r.recorded_state) ?? null)
const allRecorded = computed(() => rounds.value.length > 0 && !nextRound.value)

async function poll(): Promise<void> {
	try {
		const status = await recorderApi.status(props.session.session_token)
		rounds.value = status.rounds
		reportAvailable.value = status.report_available ?? false
		offline.value = false
		const active = status.rounds.find((r) => r.status === 'ACTIVE' && !r.recorded_state)
		blockedRound.value = active && active.id === props.blockedRoundId ? active : null
		if (active && active.id !== props.blockedRoundId) emit('start', active)
	} catch {
		offline.value = true
	}
}

async function heartbeat(): Promise<void> {
	try {
		await recorderApi.heartbeat(props.session.session_token, {
			recording_active: false,
			armed: true,
			local_chunks: 0,
			acked_chunks: 0,
			storage_ok: true,
		})
	} catch {
		/* offline — retried */
	}
}

// the whole point of this screen is waiting, so the screen must stay on:
// asleep it stops polling and heartbeating, shows as STALE to the
// organizer, and misses the round starting
useWakeLock()

onMounted(() => {
	void poll()
	void heartbeat()
	pollTimer = window.setInterval(() => void poll(), 5000)
	heartbeatTimer = window.setInterval(() => void heartbeat(), 15000)
})

onBeforeUnmount(() => {
	window.clearInterval(pollTimer)
	window.clearInterval(heartbeatTimer)
})
</script>

<template>
	<div class="rc-fill">
		<div class="rc-scroll">
			<div class="rc-hero" style="padding-top: 16px; padding-bottom: 8px">
				<p class="rc-eyebrow">{{ session.assembly.name }}</p>
				<div class="rc-hero__table">TABLE {{ session.table_number }}</div>
			</div>

			<!-- the microphone failed for the round that is currently open: say so
			     and wait to be asked, rather than silently retrying forever -->
			<template v-if="blockedRound">
				<div class="rc-card rc-center">
					<p class="rc-eyebrow" style="color: var(--rc-red)">
						{{ t('recorder.mic.blockedTitle') }}
					</p>
					<p class="rc-muted" style="margin: 0">
						{{ t('recorder.mic.blockedBody', { position: blockedRound.position }) }}
					</p>
					<button class="rc-btn rc-primary" @click="retryBlockedRound">
						{{ t('recorder.mic.retry') }}
					</button>
				</div>
			</template>

			<template v-else-if="allRecorded">
				<div class="rc-card rc-center">
					<p class="rc-eyebrow">{{ t('recorder.armed.allRecordedTitle') }}</p>
					<p class="rc-muted" style="margin: 0">{{ t('recorder.armed.allRecordedBody') }}</p>
					<button v-if="reportAvailable" class="rc-btn rc-primary" @click="emit('report')">
						{{ t('recorder.armed.viewReport') }}
					</button>
				</div>
			</template>

			<template v-else>
				<div class="rc-card rc-center">
					<p class="rc-eyebrow" style="color: var(--rc-green)">
						<span class="rc-live" style="color: var(--rc-green); display: inline-flex">ARMED</span>
					</p>
					<p style="font-size: 1.06rem; font-weight: 600; margin: 8px 0 4px">
						{{ t('recorder.armed.waiting') }}
						{{ nextRound ? `Round ${nextRound.position}` : 'the round' }}
					</p>
					<p class="rc-muted" style="margin: 0; font-size: 0.875rem">
						{{ t('recorder.armed.waitingHint') }}
					</p>
				</div>
				<div v-if="nextRound && (nextRound.question || nextRound.title)" class="rc-card">
					<p class="rc-eyebrow" style="margin-bottom: 4px">
						Round {{ nextRound.position }} · {{ nextRound.duration_minutes }} minutes
					</p>
					<p class="rc-question" style="margin: 0">{{ nextRound.question || nextRound.title }}</p>
				</div>
				<div v-if="offline" class="rc-note">
					{{ t('recorder.armed.offline') }}
				</div>
			</template>
		</div>

		<div class="rc-actions">
			<button class="rc-btn rc-subtle" @click="emit('back')">{{ t('recorder.armed.backToTest') }}</button>
		</div>
	</div>
</template>
