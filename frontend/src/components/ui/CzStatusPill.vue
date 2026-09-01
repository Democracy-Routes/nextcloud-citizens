<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = withDefaults(defineProps<{ status: string; pulse?: boolean; label?: string }>(), {
	pulse: false,
	label: '',
})

const TONE: Record<string, string> = {
	// assembly / round / recording states → tone
	DRAFT: 'gray', NOT_STARTED: 'gray', IDLE: 'gray', CREATED: 'gray',
	READY: 'blue', AUDIO_READY: 'blue',
	ACTIVE: 'red', RECORDING: 'red',
	PROCESSING: 'amber', FINALIZING: 'amber', WAITING_FOR_CHUNKS: 'amber',
	ASSEMBLING: 'amber', TRANSCRIBING: 'amber', ANALYZING: 'amber', ENDED: 'amber',
	REVIEW: 'blue', READY_FOR_REVIEW: 'blue',
	COMPLETE: 'green', TRANSCRIBED: 'green', REVIEWED: 'green', SAFE: 'green', CONNECTED: 'green',
	UPLOAD_INCOMPLETE: 'orange', AUDIO_INVALID: 'orange',
	TRANSCRIPTION_FAILED: 'orange', ANALYSIS_FAILED: 'orange', STALE: 'orange', OFFLINE: 'orange',
}

const { t, te } = useI18n()

const tone = computed(() => TONE[props.status] ?? 'gray')

/** The state, in words.
 *
 * This used to render the database enum with its underscores swapped for
 * spaces, so a facilitator read "waiting for chunks" and "audio invalid" —
 * internal vocabulary, in English, describing something they might need to act
 * on. A state with no entry still falls back to the humanized enum rather than
 * showing nothing, and the catalogue is kept complete by
 * tests/unit/test_status_labels_are_translated.py. */
const text = computed(() => {
	if (props.label) return props.label
	const key = `state.${props.status}`
	return te(key) ? t(key) : props.status.replaceAll('_', ' ').toLowerCase()
})
const shouldPulse = computed(() => props.pulse || props.status === 'ACTIVE' || props.status === 'RECORDING')
</script>

<template>
	<span class="cz-pill" :class="`cz-pill--${tone}`">
		<span class="cz-pill__dot" :class="{ 'cz-pill__dot--pulse': shouldPulse }"></span>
		{{ text }}
	</span>
</template>
