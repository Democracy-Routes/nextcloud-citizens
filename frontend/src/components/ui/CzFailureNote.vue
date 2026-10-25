<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
/**
 * Why a table failed, and what to do about it.
 *
 * A failed recording showed an orange pill reading TRANSCRIPTION_FAILED or
 * AUDIO_INVALID and nothing else — no reason, no timestamp, no next step. The
 * states differ entirely in what they need: a full disk wants space freeing
 * and a retry, invalid audio wants the table to record again, and a stalled
 * upload usually resolves itself.
 */
import { mdiAlertOutline } from '@mdi/js'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { JobInfo } from '../../types'
import SvgIcon from './SvgIcon.vue'

const props = defineProps<{ state: string; errorCode?: string; job?: JobInfo | null }>()
const { t } = useI18n()

/** What the job itself recorded, classified server-side. A provider's
 * refusal, a rate limit and a timeout all used to read "did not complete";
 * the organizer re-ran a 403 five times before anyone looked at the job row.
 * Looked up in frontend/src/i18n/organizer/results.*.json under
 * failure.reason at render time, so the locale can change under it. */
const REASON_KEYS = [
	'PROVIDER_AUTH',
	'PROVIDER_RATE_LIMIT',
	'PROVIDER_TIMEOUT',
	'PROVIDER_HTTP',
	'SCHEMA_INVALID',
	'NOT_CONFIGURED',
	'NO_TRANSCRIPT',
	'AUDIO_MISSING',
	'RERUN_EMPTY',
	'CANCELLED',
	'UNKNOWN',
]

/** Deliberately keyed on the error code, falling back to the state: the code
 * is what says which of several failures this actually was. Looked up under
 * failure.code at render time. */
const CODE_KEYS = [
	'STORAGE_FULL',
	'CHUNKS_GONE',
	'CHUNK_CORRUPTED',
	'AUDIO_DELETED',
	'UPLOAD_TIMED_OUT',
	'UPLOAD_ABANDONED',
	'RATE_LIMITED',
	'LIVE_CAPTIONS_MISSING',
	'LIVE_CAPTIONS_UNREADABLE',
	'LIVE_CAPTIONS_EMPTY',
	'DEVICE_SILENT',
	'ROUND_CONTINUED',
]

/** Looked up under failure.state at render time. */
const STATE_KEYS = ['AUDIO_INVALID', 'TRANSCRIPTION_FAILED', 'ANALYSIS_FAILED', 'UPLOAD_INCOMPLETE']

/** Specific codes win (STORAGE_FULL says more than any classifier can), then
 * the job's classified reason, then the bare state. */
const explanation = computed(() => {
	const code = props.errorCode ?? ''
	if (CODE_KEYS.includes(code)) return t(`organizer.results.failure.code.${code}`)
	const reason = props.job?.failure_reason
	if (reason && props.job?.state !== 'SUCCEEDED') {
		return t(`organizer.results.failure.reason.${REASON_KEYS.includes(reason) ? reason : 'UNKNOWN'}`)
	}
	return STATE_KEYS.includes(props.state) ? t(`organizer.results.failure.state.${props.state}`) : ''
})

const retrying = computed(() => props.job?.state === 'RETRY')

/** Seconds until the runner tries again; a snapshot — the tab's poll refreshes it. */
const retryIn = computed(() => {
	const at = props.job?.next_attempt_at
	if (!at) return null
	return Math.max(0, Math.round((new Date(at).getTime() - Date.now()) / 1000))
})

const detail = computed(() => props.job?.failure_detail ?? '')
</script>

<template>
	<p v-if="explanation || retrying" class="cz-failnote">
		<SvgIcon :path="mdiAlertOutline" :size="15" />
		<span>
			<span v-if="retrying && job" class="cz-failnote__retry">
				{{ retryIn !== null
					? t('organizer.results.failure.retryingNext', { attempt: job.attempts + 1, max: job.max_attempts, seconds: retryIn })
					: t('organizer.results.failure.retrying', { attempt: job.attempts + 1, max: job.max_attempts }) }}
			</span>
			{{ explanation }}
			<span v-if="detail" class="cz-failnote__detail">{{ detail }}</span>
		</span>
	</p>
</template>

<style scoped>
.cz-failnote {
	display: flex;
	gap: 6px;
	align-items: flex-start;
	margin: 4px 0 0;
	font-size: 0.8125rem;
	color: var(--color-text-maxcontrast, #767676);
	max-width: 46ch;
}
.cz-failnote__retry {
	font-weight: 600;
}
.cz-failnote__detail {
	display: block;
	margin-top: 2px;
	font-family: monospace;
	font-size: 0.75rem;
	opacity: 0.85;
	word-break: break-word;
}
</style>
