<!--
	SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
	SPDX-License-Identifier: AGPL-3.0-or-later

	"Participants: 3 · Add" under the table's number on the microphone test and
	the waiting screen: the way back to the notice screen for a late arrival.
	Registration is per person, not per phone, so the screen must stay
	reachable after the table has moved on. A 'required' table that cannot
	record yet says so here too, in the same words the server uses.
-->
<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { TableConsent } from '../api'

defineProps<{ consent?: TableConsent | null }>()
const emit = defineEmits<{ open: [] }>()
const { t } = useI18n()
</script>

<template>
	<button v-if="consent" type="button" class="rc-participants" :class="{ 'rc-participants--blocked': !consent.can_record }" @click="emit('open')">
		<template v-if="!consent.can_record">{{ t('recorder.consent.linkRequired') }}</template>
		<template v-else-if="consent.registered">{{ t('recorder.consent.link', { count: consent.registered }) }}</template>
		<template v-else>{{ t('recorder.consent.linkNone') }}</template>
	</button>
</template>

<style>
.rc-participants {
	display: block;
	margin: 0 16px 8px;
	background: none;
	border: 0;
	padding: 4px 0;
	color: var(--rc-blue);
	font: inherit;
	font-size: 0.8125rem;
	text-decoration: underline;
	cursor: pointer;
	min-height: 32px;
}
.rc-participants--blocked { color: #8c1d18; font-weight: 600; }
</style>
