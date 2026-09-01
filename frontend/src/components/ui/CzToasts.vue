<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
/**
 * Transient messages.
 *
 * Two problems, both invisible if you can see the screen and use a mouse. The
 * region had no live-region role, so nothing announced a toast to a screen
 * reader — the only feedback for "transcription queued" or "could not copy"
 * simply did not exist. And `pointer-events: none` on the container meant a
 * message could not be dismissed or held open, while errors expired in 3.5
 * seconds along with everything else.
 */
import { mdiAlertCircle, mdiCheckCircle, mdiClose } from '@mdi/js'
import SvgIcon from './SvgIcon.vue'
import { dismissToast, toasts } from './toast'
</script>

<template>
	<div class="cz-toasts">
		<TransitionGroup name="cz-toast">
			<div
				v-for="item in toasts"
				:key="item.id"
				class="cz-toast"
				:class="`cz-toast--${item.tone}`"
				:role="item.tone === 'error' ? 'alert' : 'status'"
				:aria-live="item.tone === 'error' ? 'assertive' : 'polite'">
				<SvgIcon :path="item.tone === 'success' ? mdiCheckCircle : mdiAlertCircle" :size="18" />
				<span class="cz-toast__text">{{ item.text }}</span>
				<button
					class="cz-toast__close"
					type="button"
					:aria-label="$t('toast.dismiss')"
					@click="dismissToast(item.id)">
					<SvgIcon :path="mdiClose" :size="16" />
				</button>
			</div>
		</TransitionGroup>
	</div>
</template>

<style scoped>
.cz-toast__text {
	flex: 1;
	min-width: 0;
}
.cz-toast__close {
	display: inline-flex;
	align-items: center;
	justify-content: center;
	min-width: 32px;
	min-height: 32px;
	padding: 0;
	border: none;
	background: none;
	color: inherit;
	cursor: pointer;
	opacity: 0.75;
}
.cz-toast__close:hover,
.cz-toast__close:focus-visible {
	opacity: 1;
}
</style>
