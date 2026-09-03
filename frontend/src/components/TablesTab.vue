<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import { mdiContentCopy, mdiShuffleVariant, mdiTableFurniture } from '@mdi/js'
import { onMounted, ref, watch } from 'vue'
import { api } from '../api'
import { describeError, type UiError } from '../errors'
import type { AssemblyDetail, Table } from '../types'
import CzButton from './ui/CzButton.vue'
import CzEmptyState from './ui/CzEmptyState.vue'
import CzError from './ui/CzError.vue'
import CzSkeleton from './ui/CzSkeleton.vue'

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
					Round {{ round.position }} — {{ round.title || 'Untitled' }}
				</option>
			</select>
			<CzButton variant="primary" small :icon="mdiShuffleVariant" :disabled="busy || !roundId" @click="randomize">
				Random assignment
			</CzButton>
			<CzButton small :icon="mdiContentCopy" :disabled="busy || !roundId" @click="copyPrevious">
				Copy previous round
			</CzButton>
		</div>

		<CzSkeleton v-if="!loaded" :rows="3" :height="120" />

		<CzEmptyState
			v-else-if="tables.length === 0"
			:icon="mdiTableFurniture"
			title="No tables in this round"
			hint="Tables are created with the round, from the assembly's table count. If that
			      count was zero this round has no tables and no QR codes, and adding another
			      round will not help — the assembly needs to be created again." />

		<CzEmptyState
			v-else-if="!hasAssignments()"
			:icon="mdiShuffleVariant"
			title="Nobody is seated yet"
			hint="Randomly assign all participants to tables, or copy the previous round's seating.">
			<CzButton variant="primary" :icon="mdiShuffleVariant" :disabled="busy" @click="randomize">
				Random assignment
			</CzButton>
		</CzEmptyState>

		<div v-else class="cz-tables-grid">
			<div v-for="table in tables" :key="table.id" class="cz-card" style="margin-bottom: 0">
				<div class="cz-row cz-row--spread" style="margin-bottom: 10px">
					<h3>Table {{ table.number }}</h3>
					<span class="cz-pill cz-pill--gray" style="text-transform: none">
						{{ table.participants.length }} seated
					</span>
				</div>
				<p v-if="table.participants.length === 0" class="cz-muted" style="font-size: 0.8125rem">Empty</p>
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
						title="Move to table"
						style="padding: 3px 6px; font-size: 0.8125rem"
						@change="
							move(
								participant.id,
								($event.target as HTMLSelectElement).value,
								$event.target as HTMLSelectElement,
								table.id,
							)
						">
						<option v-for="target in tables" :key="target.id" :value="target.id">T{{ target.number }}</option>
					</select>
				</div>
			</div>
		</div>
	</div>
</template>
