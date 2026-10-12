<!--
	SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
	SPDX-License-Identifier: AGPL-3.0-or-later

	One person's registration: name (required), email (optional), the
	required acceptance (recording, transcription, analysis) and the optional
	quotations box, ticked by default. The same form on the table's shared
	phone (ConsentScreen) and on a person's own phone (RegisterPage); the
	parent sends it. Each box's sentence is the notice's own paragraph, so what
	is ticked is exactly what the stored hash covers; Confirm needs the name
	and the required box. "This person does not consent" needs only the name
	and records a refusal. With `fixedName` the form records a change of mind
	for someone already on the roster: the name is theirs, not editable.
-->
<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

export interface ConsentFormValue {
	name: string
	email: string
	accepted: boolean
	/** short anonymous quotations in the report: optional, default yes */
	quotations: boolean
}

const props = defineProps<{
	busy?: boolean
	failed?: string
	/** "I" rather than "this person" */
	self?: boolean
	/** the notice's acceptance sentence; the catalogue's when absent */
	acceptance?: string
	/** the notice's quotations sentence; the catalogue's when absent */
	acceptanceQuotations?: string
	/** a person already on the roster who changed their mind: no refusal, no email */
	fixedName?: string
}>()
const emit = defineEmits<{ confirm: [value: ConsentFormValue]; refuse: [value: ConsentFormValue]; cancel: [] }>()

const { t } = useI18n()

const form = ref<ConsentFormValue>({ name: props.fixedName ?? '', email: '', accepted: false, quotations: true })

const canConfirm = computed(() => form.value.name.trim().length > 0 && form.value.accepted)
const sentence = computed(() => props.acceptance || t('recorder.consent.form.accept'))
const sentenceQuotations = computed(
	() => props.acceptanceQuotations || t('recorder.consent.form.acceptQuotations'),
)

function value(): ConsentFormValue {
	return { ...form.value, name: form.value.name.trim(), email: form.value.email.trim() }
}
</script>

<template>
	<div>
		<label class="rc-field">
			<span>{{ t('recorder.consent.form.name') }}</span>
			<input v-model="form.name" type="text" autocomplete="name" maxlength="200" :disabled="!!fixedName" data-test="name" />
		</label>
		<label v-if="!fixedName" class="rc-field">
			<span>{{ t('recorder.consent.form.email') }}</span>
			<input v-model="form.email" type="email" autocomplete="email" maxlength="200" data-test="email" />
		</label>
		<div class="rc-ticks">
			<label class="rc-tick">
				<input v-model="form.accepted" type="checkbox" data-test="accept" />
				<span>{{ sentence }}</span>
			</label>
			<!-- optional, ticked by default: declining withholds the table's quotations -->
			<label class="rc-tick">
				<input v-model="form.quotations" type="checkbox" data-test="quotations" />
				<span>{{ sentenceQuotations }}</span>
			</label>
		</div>
		<p v-if="failed" class="rc-alert">{{ failed }}</p>
		<button class="rc-btn rc-primary" :disabled="!canConfirm || busy" data-test="confirm" @click="emit('confirm', value())">
			{{ t('recorder.consent.form.confirm') }}
		</button>
		<button v-if="!fixedName" class="rc-btn" :disabled="!form.name.trim() || busy" data-test="refuse" @click="emit('refuse', value())">
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
