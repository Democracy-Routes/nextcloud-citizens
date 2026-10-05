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
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { setLocale } from '../../i18n'
import { recorderApi, type ParticipantStatus } from '../api'
import ReportScreen from './ReportScreen.vue'
import TableBadge from './TableBadge.vue'

const props = defineProps<{ token: string }>()
const emit = defineEmits<{ forget: [] }>()

const { t } = useI18n()

const status = ref<ParticipantStatus | null>(null)
const gone = ref(false)
const showReport = ref(false)
let poll = 0

async function load(): Promise<void> {
	try {
		status.value = await recorderApi.participantStatus(props.token)
		setLocale(status.value.assembly.language)
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
				<ul v-if="status.consent" class="rc-consent-summary" data-test="consent">
					<li :class="status.consent.recording ? 'rc-yes' : 'rc-no'">{{ t('recorder.participant.recording') }}</li>
					<li :class="status.consent.transcription ? 'rc-yes' : 'rc-no'">{{ t('recorder.participant.transcription') }}</li>
					<li :class="status.consent.analysis ? 'rc-yes' : 'rc-no'">{{ t('recorder.participant.analysis') }}</li>
					<li :class="status.consent.publication ? 'rc-yes' : 'rc-no'">{{ t('recorder.participant.publication') }}</li>
				</ul>
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
		</div>

		<div v-else class="rc-pad rc-center"><p class="rc-muted">…</p></div>
	</div>
</template>

<style scoped>
.rc-pad { padding: 6px 2px calc(12px + env(safe-area-inset-bottom, 0px)); }
.rc-lead { font-size: 1.02rem; line-height: 1.5; margin: 8px 0 0; }
.rc-consent-summary { list-style: none; margin: 0; padding: 0; }
.rc-consent-summary li { padding: 6px 0; border-bottom: 1px solid var(--rc-border); }
.rc-consent-summary li::before { content: '✓ '; font-weight: 700; }
.rc-consent-summary .rc-no::before { content: '✗ '; }
.rc-yes { color: #1e6b3a; }
.rc-no { color: #8c1d18; }
</style>
