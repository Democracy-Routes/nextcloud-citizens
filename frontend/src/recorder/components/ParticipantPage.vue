<!--
	SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
	SPDX-License-Identifier: AGPL-3.0-or-later

	A participant's own page, after registering on their phone: where they are
	registered, what they consented to, whom to contact to withdraw, and the
	published report once the organizer publishes it — the same report the
	table phones read. Polls the status while the page is open; the report
	may come days later, and the bearer outlives the event for that.
-->
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { setLocale } from '../../i18n'
import { recorderApi, type ParticipantStatus, type PublishedReport } from '../api'
import ReportScreen from './ReportScreen.vue'
import TableBadge from './TableBadge.vue'

const props = defineProps<{ token: string }>()
const emit = defineEmits<{ forget: [] }>()

const { t } = useI18n()

const status = ref<ParticipantStatus | null>(null)
const gone = ref(false)
const showReport = ref(false)
let poll = 0

/* ---- "Does this reflect your table?" ----
 * Once the report is out, the summary of the table this person sat at, per
 * session, with Looks right / Something is missing (+ a note). One answer per
 * session; the organizer sees counts and notes, never a vote. */
const report = ref<PublishedReport | null>(null)
const noteFor = ref<Record<string, string>>({})
const noteOpen = ref<string | null>(null)
const validating = ref(false)

const toValidate = computed(() => {
	if (!status.value?.rounds || !report.value) return []
	return status.value.rounds
		.filter((r) => r.table_number !== null)
		.map((r) => {
			const round = report.value!.rounds.find((x) => x.position === r.position)
			const table = round?.tables.find((t) => t.table_number === r.table_number)
			return { round: r, heading: round?.heading ?? round?.title ?? r.title, summary: table?.summary ?? '' }
		})
		.filter((entry) => entry.summary)
})

async function loadReport(): Promise<void> {
	if (report.value) return
	try {
		report.value = await recorderApi.participantReport(props.token)
	} catch {
		/* not published after all, or a blink: nothing to validate yet */
	}
}

async function validate(roundId: string, verdict: 'LOOKS_RIGHT' | 'MISSING'): Promise<void> {
	if (validating.value) return
	validating.value = true
	try {
		const answer = await recorderApi.validateSummary(props.token, roundId, verdict, noteFor.value[roundId] ?? '')
		if (status.value) {
			status.value = {
				...status.value,
				validations: { ...(status.value.validations ?? {}), [roundId]: { verdict: answer.verdict as 'LOOKS_RIGHT' | 'MISSING', note: answer.note } },
			}
		}
		noteOpen.value = null
	} catch {
		/* the next tap will say */
	} finally {
		validating.value = false
	}
}

async function load(): Promise<void> {
	try {
		status.value = await recorderApi.participantStatus(props.token)
		setLocale(status.value.assembly.language)
		if (status.value.report_available) void loadReport()
	} catch (err) {
		// an expired or erased registration: the page has nothing to show
		if (/HTTP 40[14]/.test(err instanceof Error ? err.message : '')) gone.value = true
	}
}

onMounted(() => {
	void load()
	poll = window.setInterval(() => void load(), 30_000)
})
onBeforeUnmount(() => window.clearInterval(poll))
</script>

<template>
	<ReportScreen
		v-if="showReport && status"
		:token="token"
		participant
		:assembly-name="status.assembly.name"
		:table-number="status.table_number ?? 0"
		@back="showReport = false" />

	<div v-else class="rc-scroll">
		<div v-if="gone" class="rc-pad rc-center">
			<h1 style="margin-top: 12vh">{{ t('recorder.participant.goneTitle') }}</h1>
			<p class="rc-lead">{{ t('recorder.participant.goneBody') }}</p>
			<button class="rc-btn rc-subtle" @click="emit('forget')">{{ t('recorder.participant.forget') }}</button>
		</div>

		<div v-else-if="status" class="rc-pad">
			<p class="rc-eyebrow">{{ status.assembly.name }}</p>
			<div v-if="status.table_number" style="margin: 4px 0 10px">
				<TableBadge :number="status.table_number" :color-key="status.color_key" />
			</div>
			<h1>{{ t('recorder.participant.title', { name: status.participant.name }) }}</h1>
			<p v-if="status.table_number" class="rc-lead">
				{{ t('recorder.participant.registeredAt', { number: status.table_number }) }}
			</p>

			<div class="rc-card" style="margin-top: 16px; text-align: left">
				<p class="rc-eyebrow" style="margin-bottom: 6px">{{ t('recorder.participant.consentTitle') }}</p>
				<!-- one acceptance was signed, so one line says what it covered -->
				<p
					v-if="status.consent"
					class="rc-consent-line"
					:class="status.consent.recording ? 'rc-yes' : 'rc-no'"
					data-test="consent">
					{{ status.consent.recording ? t('recorder.participant.consentedAll') : t('recorder.participant.refusedAll') }}
				</p>
				<p class="rc-muted" style="font-size: 0.8125rem; margin: 10px 0 0">
					{{
						status.contact
							? t('recorder.participant.withdraw', { contact: status.contact })
							: t('recorder.participant.withdrawNoContact', { controller: status.controller })
					}}
				</p>
			</div>

			<div class="rc-card rc-center" style="margin-top: 12px">
				<template v-if="status.report_available">
					<p style="margin: 0 0 10px">{{ t('recorder.participant.reportReady') }}</p>
					<button class="rc-btn rc-primary" data-test="report" @click="showReport = true">
						{{ t('recorder.participant.viewReport') }}
					</button>
				</template>
				<p v-else class="rc-muted" style="margin: 0">{{ t('recorder.participant.reportPending') }}</p>
			</div>

			<!-- the summary of the table this person sat at, per session, and
			     their word on it -->
			<div v-for="entry in toValidate" :key="entry.round.id" class="rc-card" style="margin-top: 12px; text-align: left" data-test="validate">
				<p class="rc-eyebrow" style="margin-bottom: 4px">
					{{ entry.heading }} · {{ t('recorder.common.tableBadge', { number: entry.round.table_number }) }}
				</p>
				<p style="font-size: 0.9375rem; margin: 0 0 10px; line-height: 1.5">{{ entry.summary }}</p>
				<template v-if="status.validations?.[entry.round.id]">
					<p class="rc-consent-line" :class="status.validations[entry.round.id].verdict === 'LOOKS_RIGHT' ? 'rc-yes' : 'rc-no'" data-test="answered">
						{{
							status.validations[entry.round.id].verdict === 'LOOKS_RIGHT'
								? t('recorder.participant.saidLooksRight')
								: t('recorder.participant.saidMissing')
						}}
					</p>
				</template>
				<template v-else>
					<p class="rc-muted" style="font-size: 0.875rem; margin: 0 0 8px">{{ t('recorder.participant.validateAsk') }}</p>
					<button class="rc-btn rc-primary" style="margin-top: 0" :disabled="validating" data-test="looks-right" @click="validate(entry.round.id, 'LOOKS_RIGHT')">
						{{ t('recorder.participant.looksRight') }}
					</button>
					<button v-if="noteOpen !== entry.round.id" class="rc-btn" :disabled="validating" data-test="missing" @click="noteOpen = entry.round.id">
						{{ t('recorder.participant.missing') }}
					</button>
					<template v-else>
						<textarea
							v-model="noteFor[entry.round.id]"
							class="rc-textarea"
							rows="3"
							maxlength="1000"
							:placeholder="t('recorder.participant.missingPlaceholder')"
							data-test="note"></textarea>
						<button class="rc-btn" :disabled="validating" data-test="send-missing" @click="validate(entry.round.id, 'MISSING')">
							{{ t('recorder.participant.sendMissing') }}
						</button>
					</template>
				</template>
			</div>
		</div>

		<div v-else class="rc-pad rc-center"><p class="rc-muted">…</p></div>
	</div>
</template>

<style scoped>
.rc-pad { padding: 6px 2px calc(12px + env(safe-area-inset-bottom, 0px)); }
.rc-lead { font-size: 1.02rem; line-height: 1.5; margin: 8px 0 0; }
.rc-consent-line { margin: 0; line-height: 1.45; font-weight: 600; }
.rc-textarea {
	width: 100%;
	box-sizing: border-box;
	font: inherit;
	padding: 10px 12px;
	border: 1px solid var(--rc-border);
	border-radius: 12px;
	background: var(--rc-surface);
	color: inherit;
	margin: 6px 0 4px;
}
.rc-consent-line::before { content: '✓ '; }
.rc-consent-line.rc-no::before { content: '✗ '; }
.rc-yes { color: #1e6b3a; }
.rc-no { color: #8c1d18; }
</style>
