<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
/**
 * A failure, said in a sentence.
 *
 * role="alert" so it is announced rather than silently appearing; the raw
 * server text is kept behind a disclosure because it helps whoever is debugging
 * and means nothing to the person running the event.
 */
import { mdiAlertCircleOutline } from '@mdi/js'
import type { UiError } from '../../errors'
import CzButton from './CzButton.vue'
import SvgIcon from './SvgIcon.vue'

defineProps<{ error: UiError }>()
const emit = defineEmits<{ retry: [] }>()
</script>

<template>
	<div class="cz-error-box" role="alert">
		<SvgIcon :path="mdiAlertCircleOutline" :size="20" class="cz-error-box__icon" />
		<div class="cz-error-box__body">
			<p class="cz-error-box__message">{{ error.message }}</p>
			<details v-if="error.detail && error.detail !== error.message">
				<summary>{{ $t('error.details') }}</summary>
				<code>{{ error.detail }}</code>
			</details>
		</div>
		<CzButton v-if="error.retryable" small @click="emit('retry')">
			{{ $t('error.retry') }}
		</CzButton>
	</div>
</template>

<style scoped>
.cz-error-box {
	display: flex;
	gap: 10px;
	align-items: flex-start;
	padding: 12px 14px;
	border-radius: 8px;
	background: var(--color-error, #c62828);
	color: #fff;
	margin-bottom: 14px;
}
.cz-error-box__icon {
	flex: none;
	margin-top: 1px;
}
.cz-error-box__body {
	flex: 1;
	min-width: 0;
}
.cz-error-box__message {
	margin: 0;
}
.cz-error-box details {
	margin-top: 6px;
	font-size: 0.8125rem;
	opacity: 0.9;
}
.cz-error-box summary {
	cursor: pointer;
}
.cz-error-box code {
	display: block;
	margin-top: 4px;
	word-break: break-word;
}
</style>
