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
import type { JobInfo } from '../../types'
import SvgIcon from './SvgIcon.vue'

const props = defineProps<{ state: string; errorCode?: string; job?: JobInfo | null }>()

/** What the job itself recorded, classified server-side. A provider's
 * refusal, a rate limit and a timeout all used to read "did not complete";
 * the organizer re-ran a 403 five times before anyone looked at the job row. */
const REASONS: Record<string, string> = {
	PROVIDER_AUTH:
		'The provider rejected the API key or this model (HTTP 401/403). Check the key, the plan and the model name in Settings, then run it again.',
	PROVIDER_RATE_LIMIT:
		'The provider is rate-limiting requests (HTTP 429). The job waits and retries by itself — do not start another run.',
	PROVIDER_TIMEOUT:
		'The provider did not answer in time. The job retries by itself; if it keeps failing, the provider is slow or unreachable.',
	PROVIDER_HTTP:
		'The provider returned an error. The job retries by itself unless the provider rejected the request outright.',
	SCHEMA_INVALID:
		'The model answered, but not in the required format, three times in a row. Run it again; if it repeats, try another model.',
	NOT_CONFIGURED: 'No provider is configured for this step — add the key or endpoint in Settings.',
	NO_TRANSCRIPT: 'There is no transcript to analyse. Transcribe the recording first.',
	AUDIO_MISSING: 'The audio file is missing on the server, so it cannot be transcribed again.',
	CANCELLED: 'Cancelled by an organizer. Run it again when ready.',
	UNKNOWN: 'It failed for a reason the app did not recognise; the detail below is what the server recorded.',
}

/** Deliberately keyed on the error code, falling back to the state: the code
 * is what says which of several failures this actually was. */
const EXPLANATIONS: Record<string, string> = {
	STORAGE_FULL:
		'The server ran out of space while assembling this recording. The uploaded audio is still here — free some space, then try again.',
	CHUNKS_GONE:
		'Parts of the upload are missing from storage, so the audio cannot be rebuilt. This table needs to record the round again.',
	CHUNK_CORRUPTED:
		'A piece of the upload failed its checksum, so the audio cannot be trusted. This table needs to record the round again.',
	AUDIO_DELETED: 'The audio was deleted while it was being assembled.',
	UPLOAD_TIMED_OUT:
		'The phone stopped uploading and did not come back. Whatever reached the server is kept; the table can record again.',
	UPLOAD_ABANDONED:
		'Waiting for this upload was stopped by an organizer. The audio already received is kept.',
	RATE_LIMITED:
		'The provider is rate-limiting requests (HTTP 429). The job waits and retries by itself — do not start another run.',
	LIVE_CAPTIONS_MISSING:
		'Final transcription is off and the caption session never wrote a transcript. Re-transcribe from the stored audio.',
	LIVE_CAPTIONS_UNREADABLE:
		'Final transcription is off and the caption file could not be read. Re-transcribe from the stored audio.',
	LIVE_CAPTIONS_EMPTY:
		'Final transcription is off and the captions contained no text. Re-transcribe from the stored audio.',
	DEVICE_SILENT:
		'The phone went silent mid-round and the table was released. Whatever reached the server is kept.',
}

const STATE_EXPLANATIONS: Record<string, string> = {
	AUDIO_INVALID: 'The uploaded audio could not be validated.',
	TRANSCRIPTION_FAILED:
		'The transcription provider did not return a transcript. The audio is untouched, so this can be tried again.',
	ANALYSIS_FAILED:
		'The AI analysis did not complete. The transcript is untouched, so this can be run again.',
	UPLOAD_INCOMPLETE: 'Not all of the recording reached the server.',
}

/** Specific codes win (STORAGE_FULL says more than any classifier can), then
 * the job's classified reason, then the bare state. */
const explanation = computed(() => {
	const byCode = EXPLANATIONS[props.errorCode ?? '']
	if (byCode) return byCode
	const reason = props.job?.failure_reason
	if (reason && props.job?.state !== 'SUCCEEDED') return REASONS[reason] ?? REASONS.UNKNOWN
	return STATE_EXPLANATIONS[props.state] ?? ''
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
				Retrying automatically — attempt {{ job.attempts + 1 }} of {{ job.max_attempts }}<template v-if="retryIn !== null">, next in {{ retryIn }} s</template>.
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
