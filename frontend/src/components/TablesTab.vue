<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import { roundHeading } from '../labels'
import { mdiContentCopy, mdiShuffleVariant, mdiTableFurniture } from '@mdi/js'
import { onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../api'
import { describeError, type UiError } from '../errors'
import type { AssemblyDetail, Table } from '../types'
import CzButton from './ui/CzButton.vue'
import CzEmptyState from './ui/CzEmptyState.vue'
import CzError from './ui/CzError.vue'
import CzSkeleton from './ui/CzSkeleton.vue'

const { t } = useI18n()

const props = defineProps<{ assembly: AssemblyDetail }>()

const roundId = ref(props.assembly.rounds[0]?.id ?? '')
const tables = ref<Table[]>([])
const loaded = ref(false)
const error = ref('')
const busy = ref(false)
const loadError = ref<UiError | null>(null)

async function reload(): Promise<void> {
	if (!roundId.value) {
		loaded.value = true
		return
	}
	try {
		tables.value = await api.roundTables(roundId.value)
		loadError.value = null
	} catch (err) {
		loadError.value = describeError(err)
	} finally {
		loaded.value = true
	}
}

onMounted(reload)
watch(roundId, () => {
	loaded.value = false
	void reload()
})

async function run(action: () => Promise<Table[]>): Promise<boolean> {
	if (busy.value) return false
	busy.value = true
	error.value = ''
	try {
		tables.value = await action()
		return true
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err)
		return false
	} finally {
		busy.value = false
	}
}

const randomize = () => run(() => api.randomize(roundId.value))
const copyPrevious = () => run(() => api.copyPrevious(roundId.value))

/** Seat everyone with a goal. "Meet new people" is the default: as few
 * repeated table-mates as possible, the people registered at the tables
 * included; the outcome says how many pairs still met before. */
const remixGoal = ref<'new_people' | 'random' | 'continuity'>('new_people')
const remixNote = ref('')
async function remix(): Promise<void> {
	remixNote.value = ''
	let outcome: { seated: number; repeated_pairs: number } | null = null
	const ok = await run(async () => {
		const result = await api.remix(roundId.value, remixGoal.value)
		outcome = result
		return result.tables
	})
	if (ok && outcome) {
		const o = outcome as { seated: number; repeated_pairs: number }
		remixNote.value = t(
			'organizer.setup.tables.remixNote',
			{ seated: o.seated, pairs: o.repeated_pairs },
			o.repeated_pairs,
		)
	}
}
/** Move a participant, and put the dropdown back if the server refuses.
 *
 * The select is bound with :value, so a failed move left the vnode prop
 * unchanged — Vue therefore had nothing to patch and the DOM kept showing the
 * new table. The facilitator saw somebody seated where the server did not have
 * them, and only a reload disagreed.
 */
async function move(
	participantId: string,
	toTableId: string,
	element: HTMLSelectElement,
	fromTableId: string,
): Promise<void> {
	const moved = await run(() => api.moveParticipant(roundId.value, participantId, toTableId))
	if (!moved) element.value = fromTableId
}

const hasAssignments = () => tables.value.some((t) => t.participants.length > 0)
</script>

<template>
	<div>
		<CzError v-if="loadError" :error="loadError" @retry="reload" />
		<div v-else-if="error" class="cz-error">{{ error }}</div>

		<div class="cz-row" style="margin-bottom: 16px">
			<select v-model="roundId" style="min-width: 220px">
				<option v-for="round in assembly.rounds" :key="round.id" :value="round.id">
					{{ roundHeading(round.position, round.title) }}
				</option>
			</select>
			<select v-model="remixGoal" data-test="remix-goal" :title="t('organizer.setup.tables.goalTitle')">
				<option value="new_people">{{ t('organizer.setup.tables.goal.newPeople') }}</option>
				<option value="random">{{ t('organizer.setup.tables.goal.random') }}</option>
				<option value="continuity">{{ t('organizer.setup.tables.goal.continuity') }}</option>
			</select>
			<CzButton variant="primary" small :icon="mdiShuffleVariant" :disabled="busy || !roundId" data-test="remix" @click="remix">
				{{ t('organizer.setup.tables.remix') }}
			</CzButton>
			<CzButton small :icon="mdiContentCopy" :disabled="busy || !roundId" @click="copyPrevious">
				{{ t('organizer.setup.tables.copyPrevious') }}
			</CzButton>
			<span v-if="remixNote" class="cz-muted" style="font-size: 0.8125rem" data-test="remix-note">{{ remixNote }}</span>
		</div>

		<CzSkeleton v-if="!loaded" :rows="3" :height="120" />

		<CzEmptyState
			v-else-if="tables.length === 0"
			:icon="mdiTableFurniture"
			:title="t('organizer.setup.tables.emptyTitle')"
			:hint="t('organizer.setup.tables.emptyHint')" />

		<CzEmptyState
			v-else-if="!hasAssignments()"
			:icon="mdiShuffleVariant"
			:title="t('organizer.setup.tables.unseatedTitle')"
			:hint="t('organizer.setup.tables.unseatedHint')">
			<CzButton variant="primary" :icon="mdiShuffleVariant" :disabled="busy" @click="randomize">
				{{ t('organizer.setup.tables.randomize') }}
			</CzButton>
		</CzEmptyState>

		<div v-else class="cz-tables-grid">
			<div v-for="table in tables" :key="table.id" class="cz-card" style="margin-bottom: 0">
				<div class="cz-row cz-row--spread" style="margin-bottom: 10px">
					<h3 class="cz-row" style="gap: 8px; flex-wrap: nowrap">
						<span class="cz-tabledot" :class="`cz-tabledot--${table.color_key}`" role="img" :aria-label="table.color_key"></span>
						{{ t('organizer.setup.tables.table', { number: table.number }) }}
					</h3>
					<span class="cz-pill cz-pill--gray" style="text-transform: none">
						{{ t('organizer.setup.tables.seated', { count: table.participants.length }) }}
					</span>
				</div>
				<p v-if="table.participants.length === 0" class="cz-muted" style="font-size: 0.8125rem">{{ t('organizer.setup.tables.empty') }}</p>
				<div
					v-for="participant in table.participants"
					:key="participant.id"
					class="cz-row cz-row--spread"
					style="padding: 4px 0; flex-wrap: nowrap">
					<span style="min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">
						<strong>{{ participant.label }}</strong>
						<span v-if="participant.name" class="cz-muted"> · {{ participant.name }}</span>
					</span>
					<select
						:value="table.id"
						:title="t('organizer.setup.tables.moveTo')"
						style="padding: 3px 6px; font-size: 0.8125rem"
						@change="
							move(
								participant.id,
								($event.target as HTMLSelectElement).value,
								$event.target as HTMLSelectElement,
								table.id,
							)
						">
						<option v-for="target in tables" :key="target.id" :value="target.id">{{ t('organizer.setup.tables.tableShort', { number: target.number }) }}</option>
					</select>
				</div>
			</div>
		</div>
	</div>
</template>
