<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import {
	mdiAccountGroup,
	mdiArrowRight,
	mdiDeleteOutline,
	mdiMonitorEye,
	mdiQrcode,
	mdiTableFurniture,
	mdiTimelineClockOutline,
} from '@mdi/js'
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import type { AssemblyDetail, Invite } from '../types'
import CzButton from './ui/CzButton.vue'
import CzStatusPill from './ui/CzStatusPill.vue'
import SvgIcon from './ui/SvgIcon.vue'

const props = defineProps<{ assembly: AssemblyDetail }>()
const emit = defineEmits<{
	navigate: [tab: 'rounds' | 'participants' | 'tables' | 'qr' | 'monitor']
	changed: []
	/** The parent owns the confirmation; this is only the trigger. */
	requestDelete: []
}>()

const invites = ref<Invite[]>([])

const editingDetails = ref(false)
const savingDetails = ref(false)
const detailsError = ref('')
const draft = ref({ name: '', description: '', language: 'en' })

/** Has any table started recording?
 *
 * The language decides how audio is transcribed and which model is chosen for
 * it, so changing it once recording has begun would leave one assembly with
 * transcripts in two languages and no way to tell which is which. The per-round
 * recording count is already in this payload. */
const recordingHasBegun = computed(() =>
	props.assembly.rounds.some((round) => (round.recording_count ?? 0) > 0),
)

function startEditDetails(): void {
	draft.value = {
		name: props.assembly.name,
		description: props.assembly.description,
		language: props.assembly.language,
	}
	detailsError.value = ''
	editingDetails.value = true
}

async function saveDetails(): Promise<void> {
	savingDetails.value = true
	detailsError.value = ''
	try {
		await api.updateAssembly(props.assembly.id, {
			name: draft.value.name.trim(),
			description: draft.value.description.trim(),
			// never sent once recording has begun, so a stale form cannot
			// change it behind the guard
			...(recordingHasBegun.value ? {} : { language: draft.value.language }),
		})
		editingDetails.value = false
		emit('changed')
	} catch (err) {
		detailsError.value = err instanceof Error ? err.message : String(err)
	} finally {
		savingDetails.value = false
	}
}

const editingInstructions = ref(false)
const instructionsDraft = ref('')
const savingInstructions = ref(false)

function startEditInstructions(): void {
	instructionsDraft.value = props.assembly.analysis_instructions
	editingInstructions.value = true
}

async function saveInstructions(): Promise<void> {
	savingInstructions.value = true
	try {
		await api.updateAssembly(props.assembly.id, {
			analysis_instructions: instructionsDraft.value.trim(),
		})
		editingInstructions.value = false
		emit('changed')
	} finally {
		savingInstructions.value = false
	}
}

onMounted(async () => {
	try {
		invites.value = await api.listInvites(props.assembly.id)
	} catch {
		/* non-critical */
	}
})

const activeInvites = computed(() => invites.value.filter((i) => i.active).length)
const activeRound = computed(() => props.assembly.rounds.find((r) => r.status === 'ACTIVE'))
const doneRounds = computed(
	() => props.assembly.rounds.filter((r) => ['ENDED', 'PROCESSING', 'READY_FOR_REVIEW'].includes(r.status)).length,
)

interface NextStep {
	text: string
	action: string
	tab: 'rounds' | 'participants' | 'tables' | 'qr' | 'monitor'
}

const nextStep = computed<NextStep | null>(() => {
	if (activeRound.value) {
		return { text: `Round ${activeRound.value.position} is live — watch table health and recordings.`, action: 'Open Live view', tab: 'monitor' }
	}
	if (props.assembly.rounds.length === 0) {
		return { text: 'Start by defining the discussion rounds and their questions.', action: 'Add rounds', tab: 'rounds' }
	}
	if (props.assembly.participant_count === 0) {
		return { text: 'Add participants — anonymous labels like P001 are enough.', action: 'Add participants', tab: 'participants' }
	}
	if (activeInvites.value === 0) {
		return { text: 'Generate the recorder QR codes and print one per table.', action: 'Generate QR codes', tab: 'qr' }
	}
	return { text: 'Everything is prepared. Start a round from the Live view when the discussion begins.', action: 'Open Live view', tab: 'monitor' }
})
</script>

<template>
	<div>
		<div v-if="nextStep" class="cz-card" style="display: flex; align-items: center; gap: 14px; flex-wrap: wrap">
			<div style="flex: 1; min-width: 220px">
				<h3 style="margin-bottom: 3px">Next step</h3>
				<p class="cz-muted" style="margin: 0">{{ nextStep.text }}</p>
			</div>
			<CzButton variant="primary" :icon="mdiArrowRight" @click="emit('navigate', nextStep.tab)">
				{{ nextStep.action }}
			</CzButton>
		</div>

		<div class="cz-statgrid">
			<button class="cz-stat cz-card--hover" style="background: none" @click="emit('navigate', 'participants')">
				<div class="cz-stat__icon"><SvgIcon :path="mdiAccountGroup" :size="24" /></div>
				<div>
					<div class="cz-stat__value">{{ assembly.participant_count }}<span class="cz-muted" style="font-size: 0.9375rem; font-weight: 500"> / {{ assembly.expected_participants }}</span></div>
					<div class="cz-stat__label">Participants</div>
				</div>
			</button>
			<button class="cz-stat cz-card--hover" style="background: none" @click="emit('navigate', 'tables')">
				<div class="cz-stat__icon"><SvgIcon :path="mdiTableFurniture" :size="24" /></div>
				<div>
					<div class="cz-stat__value">{{ assembly.default_table_count }}</div>
					<div class="cz-stat__label">Tables</div>
				</div>
			</button>
			<button class="cz-stat cz-card--hover" style="background: none" @click="emit('navigate', 'rounds')">
				<div class="cz-stat__icon"><SvgIcon :path="mdiTimelineClockOutline" :size="24" /></div>
				<div>
					<div class="cz-stat__value">{{ doneRounds }}<span class="cz-muted" style="font-size: 0.9375rem; font-weight: 500"> / {{ assembly.rounds.length }}</span></div>
					<div class="cz-stat__label">Rounds held</div>
				</div>
			</button>
			<button class="cz-stat cz-card--hover" style="background: none" @click="emit('navigate', 'qr')">
				<div class="cz-stat__icon"><SvgIcon :path="mdiQrcode" :size="24" /></div>
				<div>
					<div class="cz-stat__value">{{ activeInvites }}</div>
					<div class="cz-stat__label">Active QR codes</div>
				</div>
			</button>
		</div>

		<div class="cz-card">
			<div class="cz-row cz-row--spread" style="margin-bottom: 8px">
				<h3>Assembly details</h3>
				<CzButton v-if="!editingDetails" variant="tertiary" small @click="startEditDetails">
					Edit
				</CzButton>
			</div>
			<template v-if="editingDetails">
				<div v-if="detailsError" class="cz-error">{{ detailsError }}</div>
				<div class="cz-field">
					<label for="cz-assembly-name">Name</label>
					<input id="cz-assembly-name" v-model="draft.name" type="text" maxlength="200" />
				</div>
				<div class="cz-field">
					<label for="cz-assembly-description">Description</label>
					<textarea id="cz-assembly-description" v-model="draft.description" rows="2"></textarea>
				</div>
				<div class="cz-field">
					<label for="cz-assembly-language">Language</label>
					<select
						id="cz-assembly-language"
						v-model="draft.language"
						:disabled="recordingHasBegun">
						<option value="en">English</option>
						<option value="it">Italiano</option>
						<option value="de">Deutsch</option>
						<option value="fr">Français</option>
						<option value="es">Español</option>
					</select>
					<span v-if="recordingHasBegun" class="cz-muted" style="font-size: 0.78rem">
						Locked: this assembly has started recording. The language decides how
						audio is transcribed, so changing it now would leave one assembly with
						transcripts in two languages.
					</span>
				</div>
				<div class="cz-row" style="justify-content: flex-end; margin-top: 8px">
					<CzButton variant="tertiary" small @click="editingDetails = false">Cancel</CzButton>
					<CzButton
						variant="primary"
						small
						:disabled="savingDetails || !draft.name.trim()"
						@click="saveDetails">
						Save
					</CzButton>
				</div>
			</template>
			<template v-else>
				<p v-if="assembly.description" style="margin: 0; font-size: 0.875rem; white-space: pre-wrap">
					{{ assembly.description }}
				</p>
				<p v-else class="cz-muted" style="margin: 0; font-size: 0.845rem">
					No description. The name and language shown in the header are edited here.
				</p>
			</template>
		</div>

		<div class="cz-card">
			<div class="cz-row cz-row--spread" style="margin-bottom: 8px">
				<h3>AI analysis instructions</h3>
				<CzButton v-if="!editingInstructions" variant="tertiary" small @click="startEditInstructions">
					{{ assembly.analysis_instructions ? 'Edit' : 'Add' }}
				</CzButton>
			</div>
			<template v-if="editingInstructions">
				<textarea
					v-model="instructionsDraft"
					rows="3"
					style="width: 100%"
					placeholder="E.g. This assembly is about urban mobility. 'PUMS' means the city's mobility plan."></textarea>
				<div class="cz-row" style="justify-content: flex-end; margin-top: 8px">
					<CzButton variant="tertiary" small @click="editingInstructions = false">Cancel</CzButton>
					<CzButton variant="primary" small :disabled="savingInstructions" @click="saveInstructions">
						Save
					</CzButton>
				</div>
			</template>
			<p v-else-if="assembly.analysis_instructions" style="margin: 0; font-size: 0.875rem; white-space: pre-wrap">
				{{ assembly.analysis_instructions }}
			</p>
			<p v-else class="cz-muted" style="margin: 0; font-size: 0.845rem">
				Optional context given to the AI when analyzing this assembly — topic,
				local glossary, focus areas.
			</p>
		</div>

		<div class="cz-card">
			<div class="cz-row cz-row--spread" style="margin-bottom: 8px">
				<h3>Rounds</h3>
				<CzButton variant="tertiary" small :icon="mdiMonitorEye" @click="emit('navigate', 'monitor')">
					Live view
				</CzButton>
			</div>
			<p v-if="assembly.rounds.length === 0" class="cz-muted">No rounds defined yet.</p>
			<div
				v-for="round in assembly.rounds"
				:key="round.id"
				class="cz-row cz-row--spread"
				style="padding: 9px 0; border-bottom: 1px solid var(--cz-border)">
				<div class="cz-row" style="min-width: 0; flex-wrap: nowrap">
					<span class="cz-posbadge">{{ round.position }}</span>
					<div style="min-width: 0">
						<strong>{{ round.title || 'Untitled round' }}</strong>
						<p class="cz-muted" style="margin: 0; font-size: 0.8125rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">
							{{ round.question || 'No question set' }}
						</p>
					</div>
				</div>
				<div class="cz-row" style="flex-wrap: nowrap">
					<span class="cz-muted" style="font-size: 0.8125rem">{{ round.duration_minutes }} min</span>
					<CzStatusPill :status="round.status" />
				</div>
			</div>
		</div>

		<!-- Last, labelled, and away from everything else: this used to be a
		     small grey icon in the header, visually identical to Edit and Move
		     buttons elsewhere in the app. -->
		<div class="cz-card cz-dangerzone">
			<h3>Danger zone</h3>
			<p class="cz-muted" style="margin: 6px 0 12px; font-size: 0.875rem">
				Deleting this assembly permanently removes every round, recording,
				transcript, finding and report. There is no undo and no backup.
			</p>
			<CzButton variant="danger" :icon="mdiDeleteOutline" @click="emit('requestDelete')">
				Delete this assembly
			</CzButton>
		</div>
	</div>
</template>

<style scoped>
.cz-dangerzone {
	border: 1px solid var(--color-error, #c62828);
}
</style>
