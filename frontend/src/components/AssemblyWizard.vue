<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import { mdiChevronDown, mdiChevronUp, mdiDeleteOutline, mdiPlus } from '@mdi/js'
import { ref } from 'vue'
import { api } from '../api'
import type { InviteGenerated, RoundIn } from '../types'
import CzButton from './ui/CzButton.vue'

const emit = defineEmits<{ cancel: []; created: [id: string, invites: InviteGenerated[]] }>()

const step = ref(1)
const error = ref('')
const saving = ref(false)

const name = ref('')
const description = ref('')
const language = ref('en')
const recordingMode = ref<'orchestrated' | 'independent'>('orchestrated')
const expectedParticipants = ref(50)
const tableCount = ref(10)
const analysisInstructions = ref('')
const rounds = ref<RoundIn[]>([{ title: 'Round 1', question: '', duration_minutes: 30 }])

function addRound(): void {
	rounds.value.push({
		title: `Round ${rounds.value.length + 1}`,
		question: '',
		duration_minutes: 30,
	})
}

function removeRound(index: number): void {
	rounds.value.splice(index, 1)
}

function moveRound(index: number, delta: number): void {
	const target = index + delta
	if (target < 0 || target >= rounds.value.length) return
	const [item] = rounds.value.splice(index, 1)
	rounds.value.splice(target, 0, item)
}

async function submit(): Promise<void> {
	saving.value = true
	error.value = ''
	try {
		const created = await api.createAssembly({
			name: name.value.trim(),
			description: description.value,
			language: language.value,
			recording_mode: recordingMode.value,
			expected_participants: expectedParticipants.value,
			default_table_count: tableCount.value,
			analysis_instructions: analysisInstructions.value.trim(),
			rounds: rounds.value,
		})
		emit('created', created.id, created.invites)
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err)
	} finally {
		saving.value = false
	}
}
</script>

<template>
	<div class="cz-page" style="max-width: 720px">
		<h2>Create assembly</h2>
		<div class="cz-row" style="margin: 14px 0 20px; gap: 0">
			<div
				v-for="(label, index) in ['Basics', 'Rounds']"
				:key="label"
				class="cz-row"
				style="gap: 8px; flex-wrap: nowrap">
				<span
					class="cz-posbadge"
					:style="step === index + 1 ? '' : 'background: var(--cz-bg-dark); color: var(--cz-text-muted)'">
					{{ index + 1 }}
				</span>
				<strong :class="{ 'cz-muted': step !== index + 1 }">{{ label }}</strong>
				<span v-if="index === 0" style="width: 48px; height: 2px; background: var(--cz-border); margin: 0 12px"></span>
			</div>
		</div>

		<div v-if="error" class="cz-error">{{ error }}</div>

		<div v-if="step === 1" class="cz-card">
			<div class="cz-field">
				<label>Assembly name</label>
				<input v-model="name" type="text" placeholder="Bologna Mobility Assembly" />
			</div>
			<div class="cz-field">
				<label>Description (optional)</label>
				<textarea v-model="description" rows="2"></textarea>
			</div>
			<div class="cz-field">
				<label>Recording mode</label>
				<div class="cz-row">
					<label class="cz-radiocard" :class="{ 'cz-radiocard--checked': recordingMode === 'orchestrated' }" style="flex: 1; min-width: 240px; align-items: flex-start; flex-direction: column; gap: 4px">
						<span style="display: flex; align-items: center; gap: 8px">
							<input v-model="recordingMode" type="radio" value="orchestrated" />
							Live event (orchestrated)
						</span>
						<span class="cz-muted" style="font-weight: 400; font-size: 0.78rem">
							You start and end each round for all tables at once; phones record simultaneously.
						</span>
					</label>
					<label class="cz-radiocard" :class="{ 'cz-radiocard--checked': recordingMode === 'independent' }" style="flex: 1; min-width: 240px; align-items: flex-start; flex-direction: column; gap: 4px">
						<span style="display: flex; align-items: center; gap: 8px">
							<input v-model="recordingMode" type="radio" value="independent" />
							Independent tables
						</span>
						<span class="cz-muted" style="font-weight: 400; font-size: 0.78rem">
							Each table records the shared questions on its own schedule — even days apart.
						</span>
					</label>
				</div>
			</div>
			<div class="cz-field">
				<label>AI analysis instructions for this assembly (optional)</label>
				<textarea
					v-model="analysisInstructions"
					rows="2"
					placeholder="E.g. This assembly is about urban mobility. 'PUMS' means the city's mobility plan."></textarea>
				<span class="cz-muted" style="font-size: 0.78rem">
					Given to the AI when analyzing this assembly's discussions — topic context,
					local glossary, focus areas.
				</span>
			</div>
			<div class="cz-fieldgrid">
				<div class="cz-field">
					<label>Language</label>
					<select v-model="language">
						<option value="en">English</option>
						<option value="it">Italiano</option>
						<option value="de">Deutsch</option>
						<option value="fr">Français</option>
						<option value="es">Español</option>
					</select>
				</div>
				<div class="cz-field">
					<label>Expected participants</label>
					<input v-model.number="expectedParticipants" type="number" min="0" max="10000" />
				</div>
				<div class="cz-field">
					<label>Number of tables</label>
					<input v-model.number="tableCount" type="number" min="0" max="200" />
				</div>
			</div>
			<div class="cz-row" style="justify-content: flex-end; margin-top: 8px">
				<CzButton variant="tertiary" @click="emit('cancel')">Cancel</CzButton>
				<CzButton variant="primary" :disabled="!name.trim()" @click="step = 2">Continue</CzButton>
			</div>
		</div>

		<template v-else>
			<div v-for="(round, index) in rounds" :key="index" class="cz-card">
				<div class="cz-row cz-row--spread" style="margin-bottom: 10px">
					<div class="cz-row" style="flex-wrap: nowrap">
						<span class="cz-posbadge">{{ index + 1 }}</span>
						<strong>Round {{ index + 1 }}</strong>
					</div>
					<div class="cz-row" style="flex-wrap: nowrap">
						<CzButton small variant="tertiary" :icon="mdiChevronUp" :disabled="index === 0" @click="moveRound(index, -1)" />
						<CzButton small variant="tertiary" :icon="mdiChevronDown" :disabled="index === rounds.length - 1" @click="moveRound(index, 1)" />
						<CzButton small variant="tertiary" :icon="mdiDeleteOutline" :disabled="rounds.length === 1" @click="removeRound(index)" />
					</div>
				</div>
				<div class="cz-fieldgrid">
					<div class="cz-field">
						<label>Title</label>
						<input v-model="round.title" type="text" />
					</div>
					<div class="cz-field" style="max-width: 180px">
						<label>Duration (minutes)</label>
						<input v-model.number="round.duration_minutes" type="number" min="1" max="600" />
					</div>
				</div>
				<div class="cz-field" style="margin-bottom: 0">
					<label>Question / prompt</label>
					<textarea
						v-model="round.question"
						rows="2"
						placeholder="What mobility problems do people experience?"></textarea>
				</div>
			</div>
			<CzButton :icon="mdiPlus" @click="addRound">Add round</CzButton>
			<div class="cz-row" style="justify-content: flex-end; margin-top: 20px">
				<CzButton variant="tertiary" @click="step = 1">Back</CzButton>
				<CzButton variant="primary" :disabled="saving" @click="submit">
					{{ saving ? 'Creating…' : 'Create assembly' }}
				</CzButton>
			</div>
		</template>
	</div>
</template>
