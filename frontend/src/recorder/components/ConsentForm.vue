<!--
	SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
	SPDX-License-Identifier: AGPL-3.0-or-later

	One person's registration: name (required), email (optional), the ticks.
	The same form on the table's shared phone (ConsentScreen) and on a
	person's own phone (RegisterPage); the parent sends it. Confirm needs the
	name, "I have read the notice" and the recording tick; "This person does
	not consent" needs only the name and records a refusal.
-->
<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

export interface ConsentFormValue {
	name: string
	email: string
	read: boolean
	recording: boolean
	transcription: boolean
	analysis: boolean
	publication: boolean
}

defineProps<{ busy?: boolean; failed?: string; /** "I" rather than "this person" */ self?: boolean }>()
const emit = defineEmits<{ confirm: [value: ConsentFormValue]; refuse: [value: ConsentFormValue]; cancel: [] }>()

const { t } = useI18n()

const form = ref<ConsentFormValue>({
	name: '', email: '', read: false, recording: false, transcription: false, analysis: false, publication: false,
})

const canConfirm = computed(
	() => form.value.name.trim().length > 0 && form.value.read && form.value.recording,
)

function value(): ConsentFormValue {
	return { ...form.value, name: form.value.name.trim(), email: form.value.email.trim() }
}
</script>

<template>
	<div>
		<label class="rc-field">
			<span>{{ t('recorder.consent.form.name') }}</span>
			<input v-model="form.name" type="text" autocomplete="name" maxlength="200" data-test="name" />
		</label>
		<label class="rc-field">
			<span>{{ t('recorder.consent.form.email') }}</span>
			<input v-model="form.email" type="email" autocomplete="email" maxlength="200" data-test="email" />
		</label>
		<div class="rc-ticks">
			<label class="rc-tick"><input v-model="form.read" type="checkbox" data-test="read" /><span>{{ t('recorder.consent.form.read') }}</span></label>
			<label class="rc-tick"><input v-model="form.recording" type="checkbox" data-test="recording" /><span>{{ t('recorder.consent.form.recording') }}</span></label>
			<label class="rc-tick"><input v-model="form.transcription" type="checkbox" data-test="transcription" /><span>{{ t('recorder.consent.form.transcription') }}</span></label>
			<label class="rc-tick"><input v-model="form.analysis" type="checkbox" data-test="analysis" /><span>{{ t('recorder.consent.form.analysis') }}</span></label>
			<label class="rc-tick"><input v-model="form.publication" type="checkbox" data-test="publication" /><span>{{ t('recorder.consent.form.publication') }}</span></label>
		</div>
		<p v-if="failed" class="rc-alert">{{ failed }}</p>
		<button class="rc-btn rc-primary" :disabled="!canConfirm || busy" data-test="confirm" @click="emit('confirm', value())">
			{{ t('recorder.consent.form.confirm') }}
		</button>
		<button class="rc-btn" :disabled="!form.name.trim() || busy" data-test="refuse" @click="emit('refuse', value())">
			{{ self ? t('recorder.consent.form.refuseSelf') : t('recorder.consent.form.refuse') }}
		</button>
		<button class="rc-btn rc-subtle" :disabled="busy" @click="emit('cancel')">
			{{ t('recorder.consent.form.cancel') }}
		</button>
	</div>
</template>

<style>
.rc-field {
	display: block;
	margin: 16px 0 0;
}
.rc-field span {
	display: block;
	font-size: 0.8125rem;
	color: var(--rc-muted);
	margin-bottom: 4px;
}
.rc-field input {
	width: 100%;
	box-sizing: border-box;
	font: inherit;
	font-size: 1.0625rem;
	padding: 12px 14px;
	border: 1px solid var(--rc-border);
	border-radius: 12px;
	background: var(--rc-surface);
	color: inherit;
}
.rc-ticks { margin: 18px 0 8px; }
.rc-tick {
	display: flex;
	align-items: flex-start;
	gap: 12px;
	padding: 10px 0;
	border-bottom: 1px solid var(--rc-border);
	line-height: 1.4;
}
.rc-tick input {
	width: 24px;
	height: 24px;
	flex: 0 0 auto;
	margin: 0;
}
.rc-notice {
	margin: 14px 0 0;
	padding: 12px 14px;
	border: 1px solid var(--rc-border);
	border-radius: 12px;
	background: var(--rc-surface);
	font-size: 0.9375rem;
	line-height: 1.5;
}
.rc-notice p { margin: 0; }
.rc-notice p + p { margin-top: 8px; }
</style>
