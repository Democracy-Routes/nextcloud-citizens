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
import { useI18n } from 'vue-i18n'
import { api } from '../api'
import { useAsyncAction } from '../composables/useAsyncAction'
import type { AssemblyDetail } from '../types'
import CzButton from './ui/CzButton.vue'
import CzError from './ui/CzError.vue'
import CzConfirm from './ui/CzConfirm.vue'
import CzEmptyState from './ui/CzEmptyState.vue'
import CzStatusPill from './ui/CzStatusPill.vue'

const { t } = useI18n()

const props = defineProps<{ assembly: AssemblyDetail }>()
const emit = defineEmits<{ changed: [] }>()

const error = ref('')
const editingId = ref('')
const editTitle = ref('')
const editQuestion = ref('')
const editObjective = ref('')
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
	if (count === 0) return t('organizer.setup.rounds.deleteNoRecordings')
	return t('organizer.setup.rounds.deleteWithRecordings', { count }, count)
})

function startEdit(roundId: string): void {
	const round = props.assembly.rounds.find((r) => r.id === roundId)
	if (!round) return
	editingId.value = roundId
	editTitle.value = round.title
	editQuestion.value = round.question
	editObjective.value = round.objective ?? ''
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
			// an empty string clears it; the server stores "none stated" as null
			objective: editObjective.value.trim(),
			duration_minutes: editDuration.value,
		})
		editingId.value = ''
	})

/** The pre-filled title of a new round. Deliberately not translated: it is
 * data, and roundHeading() (and round_heading() in the report service) spot
 * exactly this "Round N" prefix to avoid printing "Round 1 — Round 1". */
const prefilledTitle = () => `Round ${props.assembly.rounds.length + 1}`

/* A standalone Session growing into an Assembly.
 *
 * The only real difference between the two is one discussion versus a
 * programme of several with the same people; everything else (tables, codes,
 * recordings, report) is already here. So "Add another session" on a Session
 * asks for the event's name, promotes the container, and adds the session —
 * choosing "Start a Session" first is never a mistake. */
const standalone = computed(() => props.assembly.kind === 'session')
const promoting = ref(false)
const eventName = ref(props.assembly.name)

const promoteAndAdd = () =>
	run(async () => {
		await api.promoteSession(props.assembly.rounds[0].id, eventName.value.trim())
		await api.addRound(props.assembly.id, {
			title: prefilledTitle(),
			question: '',
			duration_minutes: 30,
		})
		promoting.value = false
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
			title: prefilledTitle(),
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
			:title="t('organizer.setup.rounds.emptyTitle')"
			:hint="t('organizer.setup.rounds.emptyHint')">
			<CzButton variant="primary" :icon="mdiPlus" @click="add">{{ t('organizer.setup.rounds.addFirst') }}</CzButton>
		</CzEmptyState>

		<template v-else>
			<div v-for="round in assembly.rounds" :key="round.id" class="cz-card">
				<template v-if="editingId === round.id">
					<div class="cz-fieldgrid">
						<div class="cz-field"><label>{{ t('organizer.setup.rounds.title') }}</label><input v-model="editTitle" type="text" /></div>
						<div class="cz-field" style="max-width: 160px">
							<label>{{ t('organizer.setup.rounds.duration') }}</label><input v-model.number="editDuration" type="number" min="1" />
						</div>
					</div>
					<div class="cz-field">
						<label>{{ t('organizer.setup.rounds.question') }}</label><textarea v-model="editQuestion" rows="2"></textarea>
					</div>
					<div class="cz-field">
						<label>{{ t('organizer.setup.rounds.objective') }}</label>
						<textarea v-model="editObjective" rows="2" maxlength="2000" :placeholder="t('organizer.setup.rounds.objectivePlaceholder')"></textarea>
					</div>
					<div class="cz-row" style="justify-content: flex-end">
						<CzButton variant="tertiary" small @click="editingId = ''">{{ t('organizer.setup.rounds.cancel') }}</CzButton>
						<CzButton variant="primary" small @click="saveEdit">{{ t('organizer.setup.rounds.save') }}</CzButton>
					</div>
				</template>
				<template v-else>
					<div class="cz-row cz-row--spread" style="flex-wrap: nowrap; align-items: flex-start">
						<div class="cz-row" style="min-width: 0; flex-wrap: nowrap; align-items: flex-start">
							<span class="cz-posbadge">{{ round.position }}</span>
							<div style="min-width: 0">
								<div class="cz-row" style="gap: 8px">
									<strong>{{ round.title || t('organizer.setup.rounds.untitled') }}</strong>
									<span class="cz-muted" style="font-size: 0.8125rem">{{ t('organizer.setup.rounds.minutes', { minutes: round.duration_minutes }) }}</span>
									<CzStatusPill :status="round.status" />
								</div>
								<p style="margin: 6px 0 0; font-size: 0.9375rem">
									{{ round.question || t('organizer.setup.rounds.noQuestion') }}
								</p>
								<p v-if="round.objective" class="cz-muted" style="margin: 4px 0 0; font-size: 0.875rem">
									{{ t('organizer.setup.rounds.objectiveLine', { objective: round.objective }) }}
								</p>
							</div>
						</div>
						<div class="cz-row" style="flex-wrap: nowrap">
							<CzButton small variant="tertiary" :icon="mdiChevronUp" :disabled="busy || round.position === 1" :title="t('organizer.setup.rounds.moveUp')" @click="move(round.id, round.position - 1)" />
							<CzButton small variant="tertiary" :icon="mdiChevronDown" :disabled="busy || round.position === assembly.rounds.length" :title="t('organizer.setup.rounds.moveDown')" @click="move(round.id, round.position + 1)" />
							<CzButton small variant="tertiary" :icon="mdiPencilOutline" :title="t('organizer.setup.rounds.edit')" @click="startEdit(round.id)" />
							<CzButton
								small
								variant="tertiary"
								:icon="mdiDeleteOutline"
								:title="round.status === 'ACTIVE' ? t('organizer.setup.rounds.endBeforeDelete') : t('organizer.setup.rounds.delete')"
								:disabled="busy || round.status === 'ACTIVE'"
								@click="deleteId = round.id" />
						</div>
					</div>
				</template>
			</div>
			<!-- a Session has one discussion; a second one makes it an Assembly -->
			<template v-if="standalone">
				<div v-if="promoting" class="cz-card">
					<h3 style="margin-top: 0">{{ t('organizer.setup.rounds.promote.title') }}</h3>
					<p class="cz-muted" style="margin: 4px 0 12px; font-size: 0.875rem">
						{{ t('organizer.setup.rounds.promote.body') }}
					</p>
					<div class="cz-field">
						<label for="cz-event-name">{{ t('organizer.setup.rounds.promote.eventName') }}</label>
						<input id="cz-event-name" v-model="eventName" type="text" maxlength="200" />
					</div>
					<div class="cz-row" style="justify-content: flex-end">
						<CzButton variant="tertiary" small :disabled="busy" @click="promoting = false">{{ t('organizer.setup.rounds.cancel') }}</CzButton>
						<CzButton variant="primary" small :disabled="busy || !eventName.trim()" @click="promoteAndAdd">
							{{ t('organizer.setup.rounds.promote.confirm') }}
						</CzButton>
					</div>
				</div>
				<CzButton v-else :icon="mdiPlus" :disabled="busy" @click="promoting = true">{{ t('organizer.setup.rounds.promote.addAnother') }}</CzButton>
			</template>
			<CzButton v-else :icon="mdiPlus" :disabled="busy" @click="add">{{ t('organizer.setup.rounds.add') }}</CzButton>
		</template>

		<CzConfirm
			v-if="deleteId"
			:title="t('organizer.setup.rounds.confirmTitle')"
			:message="deleteMessage"
			:confirm-label="t('organizer.setup.rounds.confirmLabel')"
			tone="danger"
			@confirm="remove"
			@cancel="deleteId = ''" />
	</div>
</template>
