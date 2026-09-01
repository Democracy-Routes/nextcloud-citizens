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
import SvgIcon from './SvgIcon.vue'

const props = defineProps<{ state: string; errorCode?: string }>()

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
}

const STATE_EXPLANATIONS: Record<string, string> = {
	AUDIO_INVALID: 'The uploaded audio could not be validated.',
	TRANSCRIPTION_FAILED:
		'The transcription provider did not return a transcript. The audio is untouched, so this can be tried again.',
	ANALYSIS_FAILED:
		'The AI analysis did not complete. The transcript is untouched, so this can be run again.',
	UPLOAD_INCOMPLETE: 'Not all of the recording reached the server.',
}

const explanation = computed(
	() => EXPLANATIONS[props.errorCode ?? ''] ?? STATE_EXPLANATIONS[props.state] ?? '',
)
</script>

<template>
	<p v-if="explanation" class="cz-failnote">
		<SvgIcon :path="mdiAlertOutline" :size="15" />
		<span>{{ explanation }}</span>
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
</style>
