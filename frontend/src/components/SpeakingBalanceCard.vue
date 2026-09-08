<!--
	SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
	SPDX-License-Identifier: AGPL-3.0-or-later

	How much each voice spoke in a round, as a donut.

	The voices are anonymous diarization labels (A, B, C…), never names, and
	they come from ONE recording — the one that captured the most speech — because
	diarization labels are not consistent across devices. The caption says so
	plainly; overstating what this measures would be worse than not showing it.
-->
<script setup lang="ts">
import { computed } from 'vue'
import type { SpeakingBalance } from '../types'

const props = defineProps<{ balance: SpeakingBalance }>()

// Mid-toned hues that stay legible on both the light and dark card grounds.
// "Others" always takes the last, muted slot.
const PALETTE = ['#3a7bd5', '#17a398', '#e08b2d', '#b0559b', '#5aa02c', '#d6564e']
const OTHERS = '#8a8f98'

const R = 42
const CIRC = 2 * Math.PI * R

function colorFor(index: number, label: string): string {
	return label === 'Others' ? OTHERS : PALETTE[index % PALETTE.length]
}

const segments = computed(() => {
	let offset = 0
	return props.balance.voices.map((v, i) => {
		const len = (v.percent / 100) * CIRC
		const seg = {
			color: colorFor(i, v.label),
			// a hair of gap so adjacent slices read as separate
			dash: `${Math.max(0, len - 0.8)} ${CIRC - Math.max(0, len - 0.8)}`,
			offset: -offset,
		}
		offset += len
		return seg
	})
})

function clock(seconds: number): string {
	const s = Math.round(seconds)
	return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

const legend = computed(() =>
	props.balance.voices.map((v, i) => ({
		...v,
		color: colorFor(i, v.label),
		clock: clock(v.seconds),
	})),
)
</script>

<template>
	<div class="cz-card cz-speaking">
		<span class="cz-muted cz-speaking__eyebrow">SPEAKING BALANCE</span>
		<div class="cz-speaking__body">
			<svg
				class="cz-speaking__donut"
				viewBox="0 0 120 120"
				role="img"
				aria-label="Share of speaking time per detected voice">
				<g transform="rotate(-90 60 60)">
					<circle cx="60" cy="60" :r="R" fill="none" stroke="var(--cz-border)" stroke-width="14" />
					<circle
						v-for="(seg, i) in segments"
						:key="i"
						cx="60"
						cy="60"
						:r="R"
						fill="none"
						:stroke="seg.color"
						stroke-width="14"
						:stroke-dasharray="seg.dash"
						:stroke-dashoffset="seg.offset" />
				</g>
			</svg>
			<ul class="cz-speaking__legend">
				<li v-for="v in legend" :key="v.label">
					<span class="cz-speaking__swatch" :style="{ background: v.color }"></span>
					<span class="cz-speaking__name">Voice {{ v.label }}</span>
					<span class="cz-speaking__pct">{{ v.percent }}%</span>
					<span class="cz-muted cz-speaking__time">{{ v.clock }}</span>
				</li>
			</ul>
		</div>
		<p class="cz-muted cz-speaking__note">
			Detected voices, not identified by name — from the clearest single recording. An estimate of
			talk-time, not of participation or influence.
		</p>
	</div>
</template>

<style scoped>
.cz-speaking__eyebrow {
	font-size: 0.75rem;
	letter-spacing: 0.04em;
	display: block;
	margin-bottom: 12px;
}
.cz-speaking__body {
	display: flex;
	align-items: center;
	gap: 24px;
	flex-wrap: wrap;
}
.cz-speaking__donut {
	width: 132px;
	height: 132px;
	flex: 0 0 auto;
}
.cz-speaking__legend {
	list-style: none;
	margin: 0;
	padding: 0;
	flex: 1 1 220px;
	min-width: 200px;
}
.cz-speaking__legend li {
	display: flex;
	align-items: center;
	gap: 8px;
	padding: 3px 0;
	font-size: 0.9rem;
}
.cz-speaking__swatch {
	width: 12px;
	height: 12px;
	border-radius: 3px;
	flex: 0 0 auto;
}
.cz-speaking__name {
	flex: 1 1 auto;
}
.cz-speaking__pct {
	font-variant-numeric: tabular-nums;
	font-weight: 600;
}
.cz-speaking__time {
	font-variant-numeric: tabular-nums;
	font-size: 0.8125rem;
	min-width: 3ch;
	text-align: right;
}
.cz-speaking__note {
	font-size: 0.8125rem;
	margin: 12px 0 0;
}
</style>
