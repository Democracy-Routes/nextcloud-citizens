<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import {
	mdiChevronDown,
	mdiChevronUp,
	mdiDeleteOutline,
	mdiPencilOutline,
	mdiPlus,
	mdiTimelineClockOutline,
} from '@mdi/js'
import { computed, ref } from 'vue'
import { api } from '../api'
import { useAsyncAction } from '../composables/useAsyncAction'
import type { AssemblyDetail } from '../types'
import CzButton from './ui/CzButton.vue'
import CzError from './ui/CzError.vue'
import CzConfirm from './ui/CzConfirm.vue'
import CzEmptyState from './ui/CzEmptyState.vue'
import CzStatusPill from './ui/CzStatusPill.vue'

const props = defineProps<{ assembly: AssemblyDetail }>()
const emit = defineEmits<{ changed: [] }>()

const error = ref('')
const editingId = ref('')
const editTitle = ref('')
const editQuestion = ref('')
const editDuration = ref(30)
const deleteId = ref('')

/** Name what the delete actually destroys.
 *
 * "any recordings made in it" gave the facilitator no way to tell an empty
 * round from one holding an hour of audio from eight tables.
 */
const deleteMessage = computed(() => {
	const round = props.assembly.rounds.find((r) => r.id === deleteId.value)
	const count = round?.recording_count ?? 0
	if (count === 0) return 'The round and its tables will be deleted. It has no recordings.'
	const plural = count === 1 ? 'recording' : 'recordings'
	return `The round, its tables and its ${count} ${plural} will be permanently deleted, including the audio.`
})

function startEdit(roundId: string): void {
	const round = props.assembly.rounds.find((r) => r.id === roundId)
	if (!round) return
	editingId.value = roundId
	editTitle.value = round.title
	editQuestion.value = round.question
	editDuration.value = round.duration_minutes
}

const { busy, error: actionError, run: runGuarded } = useAsyncAction()

async function run(action: () => Promise<unknown>): Promise<void> {
	// the guard is the point: the reorder arrows had none, so a double-click
	// fired two PUTs and the round could end up two places away
	if (await runGuarded(action)) emit('changed')
}

const saveEdit = () =>
	run(async () => {
		await api.updateRound(editingId.value, {
			title: editTitle.value,
			question: editQuestion.value,
			duration_minutes: editDuration.value,
		})
		editingId.value = ''
	})

const move = (roundId: string, position: number) => run(() => api.updateRound(roundId, { position }))
const remove = () =>
	run(async () => {
		await api.deleteRound(deleteId.value)
		deleteId.value = ''
	})
const add = () =>
	run(() =>
		api.addRound(props.assembly.id, {
			title: `Round ${props.assembly.rounds.length + 1}`,
			question: '',
			duration_minutes: 30,
		}),
	)
</script>

<template>
	<div>
		<CzError v-if="actionError" :error="actionError" />
		<div v-else-if="error" class="cz-error">{{ error }}</div>

		<CzEmptyState
			v-if="assembly.rounds.length === 0"
			:icon="mdiTimelineClockOutline"
			title="No rounds yet"
			hint="Each round is one table discussion with its own question and duration.">
			<CzButton variant="primary" :icon="mdiPlus" @click="add">Add the first round</CzButton>
		</CzEmptyState>

		<template v-else>
			<div v-for="round in assembly.rounds" :key="round.id" class="cz-card">
				<template v-if="editingId === round.id">
					<div class="cz-fieldgrid">
						<div class="cz-field"><label>Title</label><input v-model="editTitle" type="text" /></div>
						<div class="cz-field" style="max-width: 160px">
							<label>Duration (min)</label><input v-model.number="editDuration" type="number" min="1" />
						</div>
					</div>
					<div class="cz-field">
						<label>Question / prompt</label><textarea v-model="editQuestion" rows="2"></textarea>
					</div>
					<div class="cz-row" style="justify-content: flex-end">
						<CzButton variant="tertiary" small @click="editingId = ''">Cancel</CzButton>
						<CzButton variant="primary" small @click="saveEdit">Save round</CzButton>
					</div>
				</template>
				<template v-else>
					<div class="cz-row cz-row--spread" style="flex-wrap: nowrap; align-items: flex-start">
						<div class="cz-row" style="min-width: 0; flex-wrap: nowrap; align-items: flex-start">
							<span class="cz-posbadge">{{ round.position }}</span>
							<div style="min-width: 0">
								<div class="cz-row" style="gap: 8px">
									<strong>{{ round.title || 'Untitled round' }}</strong>
									<span class="cz-muted" style="font-size: 0.8125rem">{{ round.duration_minutes }} min</span>
									<CzStatusPill :status="round.status" />
								</div>
								<p style="margin: 6px 0 0; font-size: 0.9375rem">
									{{ round.question || 'No question set yet.' }}
								</p>
							</div>
						</div>
						<div class="cz-row" style="flex-wrap: nowrap">
							<CzButton small variant="tertiary" :icon="mdiChevronUp" :disabled="busy || round.position === 1" title="Move up" @click="move(round.id, round.position - 1)" />
							<CzButton small variant="tertiary" :icon="mdiChevronDown" :disabled="busy || round.position === assembly.rounds.length" title="Move down" @click="move(round.id, round.position + 1)" />
							<CzButton small variant="tertiary" :icon="mdiPencilOutline" title="Edit" @click="startEdit(round.id)" />
							<CzButton
								small
								variant="tertiary"
								:icon="mdiDeleteOutline"
								:title="round.status === 'ACTIVE' ? 'End the round before deleting it' : 'Delete'"
								:disabled="busy || round.status === 'ACTIVE'"
								@click="deleteId = round.id" />
						</div>
					</div>
				</template>
			</div>
			<CzButton :icon="mdiPlus" :disabled="busy" @click="add">Add round</CzButton>
		</template>

		<CzConfirm
			v-if="deleteId"
			title="Delete round?"
			:message="deleteMessage"
			confirm-label="Delete round"
			tone="danger"
			@confirm="remove"
			@cancel="deleteId = ''" />
	</div>
</template>
