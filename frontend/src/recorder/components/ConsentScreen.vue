<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
/**
 * Shown once per device before anything is recorded (brief §43).
 *
 * People at the table are about to have their voices recorded, so they are
 * told in plain language what happens to that audio: which engine transcribes
 * it, whether that engine belongs to somebody else, and how long the recording
 * is kept. Everything here comes from the server's live configuration, so it
 * cannot drift from what the app actually does.
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { DataHandling } from '../api'

const props = defineProps<{ handling: DataHandling | null; tableNumber: number }>()
const emit = defineEmits<{ (event: 'accept'): void }>()

const { t } = useI18n()

/** Somebody at the table objects. Consent that offers only one button is not
 * consent, and a table with no way to say no had to work it out by walking
 * away from the phone. */
const declined = ref(false)

const ENGINE_NAMES: Record<string, string> = {
	deepgram: 'Deepgram',
	mistral: 'Mistral',
	whisper: 'Whisper',
	vosk: 'Vosk',
}

const engine = computed(
	() => ENGINE_NAMES[props.handling?.stt_provider ?? ''] ?? t('recorder.consent.engineFallback'),
)

const audioDestination = computed(() => {
	if (!props.handling) return t('recorder.consent.notConfigured')
	if (!props.handling.stt_configured) return t('recorder.consent.noEngine')
	return props.handling.stt_hosted
		? t('recorder.consent.audioHosted', { engine: engine.value })
		: t('recorder.consent.audioSelfHosted', { engine: engine.value })
})

const transcriptDestination = computed(() => {
	if (!props.handling?.analysis_enabled) return null
	return props.handling.analysis_hosted
		? t('recorder.consent.transcriptHosted')
		: t('recorder.consent.transcriptSelfHosted')
})

const retention = computed(() => {
	const days = props.handling?.audio_retention_days ?? 0
	if (days > 0) return t('recorder.consent.retentionDays', { days }, days)
	return t('recorder.consent.retentionForever')
})
</script>

<template>
	<div class="rc-scroll">
		<div v-if="declined" class="rc-pad">
			<h1>{{ t('recorder.consent.declinedTitle') }}</h1>
			<p class="rc-lead">{{ t('recorder.consent.declinedBody') }}</p>
			<button class="rc-btn rc-btn--block" @click="declined = false">
				{{ t('recorder.consent.declinedBack') }}
			</button>
		</div>

		<div v-else class="rc-pad">
			<h1>{{ t('recorder.consent.title', { number: tableNumber }) }}</h1>
			<p class="rc-lead">{{ t('recorder.consent.lead') }}</p>

			<ul class="rc-consent">
				<li>{{ t('recorder.consent.records') }}</li>
				<li>{{ audioDestination }}</li>
				<li v-if="transcriptDestination">{{ transcriptDestination }}</li>
				<li>{{ retention }}</li>
				<li>{{ t('recorder.consent.speakers') }}</li>
				<li>{{ t('recorder.consent.reviewed') }}</li>
			</ul>

			<p class="rc-muted rc-consent__ask">{{ t('recorder.consent.ask') }}</p>

			<button class="rc-btn rc-btn--primary rc-btn--block" @click="emit('accept')">
				{{ t('recorder.consent.agree') }}
			</button>
			<button class="rc-btn rc-btn--block rc-subtle" @click="declined = true">
				{{ t('recorder.consent.decline') }}
			</button>
		</div>
	</div>
</template>

<style scoped>
.rc-consent {
	margin: 18px 0 0;
	padding-left: 20px;
	line-height: 1.55;
}
.rc-consent li + li {
	margin-top: 10px;
}
.rc-consent__ask {
	margin: 20px 0 18px;
}
</style>
