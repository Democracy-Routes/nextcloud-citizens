<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
/**
 * When this view was last known to be current.
 *
 * A failed poll used to leave the previous result on screen with nothing to
 * say so — the Live tab could show "8/8 tables connected" from several minutes
 * ago, countdown still ticking, while the server had been unreachable
 * throughout. A facilitator has no way to tell that apart from everything
 * being fine, and it is the one thing they are reading the screen for.
 */
import { mdiRefresh } from '@mdi/js'
import { computed } from 'vue'
import CzButton from './CzButton.vue'

const props = defineProps<{
	lastSuccessAt: Date | null
	consecutiveFailures: number
	busy?: boolean
}>()
const emit = defineEmits<{ refresh: [] }>()

const stale = computed(() => props.consecutiveFailures > 0)

const clock = computed(() =>
	props.lastSuccessAt
		? props.lastSuccessAt.toLocaleTimeString(undefined, {
				hour: '2-digit',
				minute: '2-digit',
				second: '2-digit',
			})
		: '—',
)
</script>

<template>
	<div class="cz-freshness" :class="{ 'cz-freshness--stale': stale }">
		<span v-if="stale" class="cz-freshness__label" role="status">
			{{ $t('freshness.reconnecting', { time: clock }) }}
		</span>
		<span v-else class="cz-freshness__label">
			{{ $t('freshness.updated', { time: clock }) }}
		</span>
		<CzButton small variant="tertiary" :icon="mdiRefresh" :disabled="busy" @click="emit('refresh')">
			{{ $t('freshness.refresh') }}
		</CzButton>
	</div>
</template>

<style scoped>
.cz-freshness {
	display: flex;
	align-items: center;
	gap: 8px;
	font-size: 0.8125rem;
	color: var(--color-text-maxcontrast, #767676);
}
.cz-freshness--stale .cz-freshness__label {
	color: var(--color-warning, #a6791a);
	font-weight: 600;
}
</style>
