<!--
	SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
	SPDX-License-Identifier: AGPL-3.0-or-later

	What the organizer just said — "5 minutes left" — shown big for a few
	seconds, then folded to one line so the table keeps its screen, then gone.
	It never covers the Finish button and never interrupts capture; it is the
	facilitator's voice reaching twenty tables without shouting.
-->
<script setup lang="ts">
import { mdiBullhornOutline } from '@mdi/js'
import { onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import SvgIcon from '../../components/ui/SvgIcon.vue'
import type { PhoneMessage } from '../api'

const props = defineProps<{ message: PhoneMessage }>()
const emit = defineEmits<{ dismiss: [] }>()

const { t } = useI18n()

/** full for six seconds, one line for a minute and a half, then gone */
const FULL_MS = 6_000
const COMPACT_MS = 90_000

const compact = ref(false)
let foldTimer = 0
let goneTimer = 0

function schedule(): void {
	window.clearTimeout(foldTimer)
	window.clearTimeout(goneTimer)
	compact.value = false
	foldTimer = window.setTimeout(() => (compact.value = true), FULL_MS)
	goneTimer = window.setTimeout(() => emit('dismiss'), FULL_MS + COMPACT_MS)
}

watch(() => props.message.id, schedule, { immediate: true })
onBeforeUnmount(() => {
	window.clearTimeout(foldTimer)
	window.clearTimeout(goneTimer)
})
</script>

<template>
	<div class="rc-message" :class="{ 'rc-message--compact': compact }" role="status" aria-live="polite">
		<SvgIcon :path="mdiBullhornOutline" :size="compact ? 16 : 22" />
		<div class="rc-message__body">
			<span v-if="!compact" class="rc-message__from">{{ t('recorder.message.from') }}</span>
			<strong class="rc-message__text">{{ message.text }}</strong>
		</div>
		<button type="button" class="rc-message__close" :aria-label="t('recorder.message.dismiss')" @click="emit('dismiss')">
			×
		</button>
	</div>
</template>

<style>
.rc-message {
	display: flex;
	align-items: flex-start;
	gap: 10px;
	margin: 8px 16px 0;
	padding: 14px 14px 14px 16px;
	border-radius: 14px;
	background: #1c4a6e;
	color: #fff;
	box-shadow: 0 4px 14px rgba(0, 0, 0, 0.18);
}
.rc-message--compact {
	padding: 8px 12px;
	align-items: center;
	background: #e8f2fa;
	color: #1c4a6e;
	box-shadow: none;
}
.rc-message__body { flex: 1; min-width: 0; }
.rc-message__from {
	display: block;
	font-size: 0.75rem;
	opacity: 0.85;
	text-transform: uppercase;
	letter-spacing: 0.04em;
}
.rc-message__text { font-size: 1.25rem; line-height: 1.3; }
.rc-message--compact .rc-message__text { font-size: 0.9375rem; }
.rc-message__close {
	background: none;
	border: 0;
	color: inherit;
	font-size: 1.5rem;
	line-height: 1;
	padding: 0 4px;
	min-width: 44px;
	min-height: 32px;
	cursor: pointer;
}
</style>
