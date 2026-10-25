<!--
	SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
	SPDX-License-Identifier: AGPL-3.0-or-later

	The event at a glance, above the Plan / Run / Results spaces (0.7): the
	sessions in order as pills with their state, the live one highlighted, and
	the headline counts — participants against the target, tables, sessions.
	Clicking a session opens the Run space on it. Nothing here is a control
	the organizer must use; it is the map the three spaces sit under.
-->
<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { AssemblyDetail } from '../types'

const props = defineProps<{ assembly: AssemblyDetail }>()
const emit = defineEmits<{ open: [roundId: string] }>()

const { t } = useI18n()

type Tone = 'gray' | 'green' | 'blue' | 'amber'

function stateOf(status: string): { label: string; tone: Tone; live: boolean } {
	switch (status) {
		case 'ACTIVE':
			return { label: t('organizer.navigation.timeline.liveNow'), tone: 'green', live: true }
		case 'ENDED':
			return { label: t('organizer.navigation.timeline.ended'), tone: 'blue', live: false }
		case 'PROCESSING':
			return { label: t('organizer.navigation.timeline.processing'), tone: 'blue', live: false }
		case 'READY_FOR_REVIEW':
		case 'REVIEWED':
			return { label: t('organizer.navigation.timeline.review'), tone: 'amber', live: false }
		default:
			return { label: t('organizer.navigation.timeline.notStarted'), tone: 'gray', live: false }
	}
}

const rounds = computed(() =>
	[...props.assembly.rounds]
		.sort((a, b) => a.position - b.position)
		.map((round) => ({ ...round, state: stateOf(round.status) })),
)

const headline = computed(() => {
	const parts: string[] = []
	if (props.assembly.kind !== 'session') {
		parts.push(
			props.assembly.expected_participants
				? t('organizer.navigation.timeline.participants', {
					count: props.assembly.participant_count,
					expected: props.assembly.expected_participants,
				})
				: t('organizer.navigation.timeline.participantsNoTarget', { count: props.assembly.participant_count }),
		)
	}
	parts.push(
		props.assembly.recording_mode === 'plenary'
			? t('organizer.navigation.timeline.wholeRoom')
			: t('organizer.navigation.timeline.tables', { count: props.assembly.default_table_count }, props.assembly.default_table_count),
	)
	parts.push(t('organizer.navigation.timeline.sessions', { count: rounds.value.length }, rounds.value.length))
	return parts
})
</script>

<template>
	<div class="cz-timeline" data-test="timeline">
		<p class="cz-timeline__headline cz-muted" data-test="headline">
			<template v-for="(part, index) in headline" :key="index">
				<span v-if="index > 0"> · </span>{{ part }}
			</template>
			<span v-if="assembly.closed_at" class="cz-pill cz-pill--gray" style="margin-left: 8px">{{ t('organizer.navigation.timeline.closed') }}</span>
		</p>
		<ol class="cz-timeline__track">
			<li v-for="round in rounds" :key="round.id">
				<button
					type="button"
					class="cz-timeline__pill"
					:class="[`cz-timeline__pill--${round.state.tone}`, { 'cz-timeline__pill--live': round.state.live }]"
					:title="t('organizer.navigation.timeline.openLive', { position: round.position })"
					:data-test="`timeline-${round.position}`"
					@click="emit('open', round.id)">
					<span class="cz-timeline__num">{{ round.position }}</span>
					<span class="cz-timeline__title">{{ round.title || t('organizer.navigation.timeline.untitled', { position: round.position }) }}</span>
					<span class="cz-timeline__state">{{ round.state.label }}</span>
				</button>
			</li>
		</ol>
	</div>
</template>

<style>
#citizens-app .cz-timeline { margin: 14px 0 4px; }
#citizens-app .cz-timeline__headline { margin: 0 0 8px; font-size: 0.875rem; display: flex; align-items: center; flex-wrap: wrap; gap: 2px; }
#citizens-app .cz-timeline__track {
	list-style: none;
	margin: 0;
	padding: 0;
	display: flex;
	gap: 8px;
	overflow-x: auto;
	scrollbar-width: none;
}
#citizens-app .cz-timeline__pill {
	display: inline-flex;
	align-items: center;
	gap: 8px;
	padding: 6px 12px 6px 8px;
	border-radius: 999px;
	border: 1px solid var(--cz-border);
	background: var(--cz-bg);
	color: var(--cz-text);
	font: inherit;
	font-size: 0.8125rem;
	cursor: pointer;
	white-space: nowrap;
}
#citizens-app .cz-timeline__pill:hover { border-color: var(--cz-primary); }
#citizens-app .cz-timeline__num {
	display: inline-flex;
	align-items: center;
	justify-content: center;
	width: 22px;
	height: 22px;
	border-radius: 50%;
	background: color-mix(in srgb, #9e9e9e 18%, var(--cz-bg));
	font-weight: 700;
	font-size: 0.75rem;
}
#citizens-app .cz-timeline__pill--green .cz-timeline__num { background: color-mix(in srgb, var(--cz-green) 22%, var(--cz-bg)); color: var(--cz-green); }
#citizens-app .cz-timeline__pill--blue .cz-timeline__num { background: color-mix(in srgb, var(--cz-blue) 18%, var(--cz-bg)); color: var(--cz-blue); }
#citizens-app .cz-timeline__pill--amber .cz-timeline__num { background: color-mix(in srgb, var(--cz-amber) 20%, var(--cz-bg)); color: var(--cz-amber); }
#citizens-app .cz-timeline__state { color: var(--cz-text-muted); font-size: 0.75rem; }
#citizens-app .cz-timeline__pill--live { border-color: var(--cz-green); box-shadow: 0 0 0 3px color-mix(in srgb, var(--cz-green) 18%, transparent); }
#citizens-app .cz-timeline__pill--live .cz-timeline__state { color: var(--cz-green); font-weight: 600; }
</style>
