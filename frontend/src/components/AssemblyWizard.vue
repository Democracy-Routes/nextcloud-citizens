<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import { mdiChevronDown, mdiChevronUp, mdiDeleteOutline, mdiPlus } from '@mdi/js'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../api'
import type { InviteGenerated, RoundIn } from '../types'
import CzButton from './ui/CzButton.vue'

const emit = defineEmits<{ cancel: []; created: [id: string, invites: InviteGenerated[]] }>()

const { t } = useI18n()

// computed, not a module constant, so the labels follow a locale change
const steps = computed(() => [
	t('organizer.shell.assemblyWizard.stepBasics'),
	t('organizer.shell.assemblyWizard.stepSessions'),
])
// option values are the server's language codes; the names are endonyms
const LANGUAGES = ['en', 'it', 'de', 'fr', 'es'] as const

const step = ref(1)
const error = ref('')
const saving = ref(false)

const name = ref('')
const description = ref('')
const language = ref('en')
const recordingMode = ref<'orchestrated' | 'independent' | 'plenary'>('orchestrated')
const expectedParticipants = ref(50)
const tableCount = ref(10)
const analysisInstructions = ref('')
const rounds = ref<RoundIn[]>([{ title: 'Round 1', question: '', duration_minutes: 30 }])

/* The component has no <form>, so the inputs' min/max never run — they only
 * drive the spinner arrows. An assembly created with zero tables gets no Table
 * rows, therefore no QR codes, therefore no phone can ever join it, and
 * nothing in the UI can repair it afterwards. */
const basicsValid = computed(() => !!name.value.trim() && tableCount.value >= 1)

// Plenary is the whole room as one group joined by one shared code, so it
// always has exactly one table (the server enforces this too).
watch(recordingMode, (mode) => {
	if (mode === 'plenary') tableCount.value = 1
})

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
			// an organized assembly asks for individual consent at the table
			// before a table records; the Overview tab can relax it
			participant_consent: 'required',
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
		<h2>{{ t('organizer.shell.assemblyWizard.title') }}</h2>
		<p class="cz-muted" style="margin: 4px 0 0">
			{{ t('organizer.shell.assemblyWizard.intro') }}
		</p>
		<div class="cz-row" style="margin: 14px 0 20px; gap: 0">
			<div
				v-for="(label, index) in steps"
				:key="index"
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
				<label>{{ t('organizer.shell.assemblyWizard.name') }}</label>
				<input v-model="name" type="text" :placeholder="t('organizer.shell.assemblyWizard.namePlaceholder')" />
			</div>
			<div class="cz-field">
				<label>{{ t('organizer.shell.assemblyWizard.description') }}</label>
				<textarea v-model="description" rows="2"></textarea>
			</div>
			<div class="cz-field">
				<label>{{ t('organizer.shell.assemblyWizard.recordingMode') }}</label>
				<div class="cz-row">
					<label class="cz-radiocard" :class="{ 'cz-radiocard--checked': recordingMode === 'orchestrated' }" style="flex: 1; min-width: 240px; align-items: flex-start; flex-direction: column; gap: 4px">
						<span style="display: flex; align-items: center; gap: 8px">
							<input v-model="recordingMode" type="radio" value="orchestrated" />
							{{ t('organizer.shell.assemblyWizard.orchestrated') }}
						</span>
						<span class="cz-muted" style="font-weight: 400; font-size: 0.78rem">
							{{ t('organizer.shell.assemblyWizard.orchestratedHint') }}
						</span>
					</label>
					<label class="cz-radiocard" :class="{ 'cz-radiocard--checked': recordingMode === 'independent' }" style="flex: 1; min-width: 240px; align-items: flex-start; flex-direction: column; gap: 4px">
						<span style="display: flex; align-items: center; gap: 8px">
							<input v-model="recordingMode" type="radio" value="independent" />
							{{ t('organizer.shell.assemblyWizard.independent') }}
						</span>
						<span class="cz-muted" style="font-weight: 400; font-size: 0.78rem">
							{{ t('organizer.shell.assemblyWizard.independentHint') }}
						</span>
					</label>
					<label class="cz-radiocard" :class="{ 'cz-radiocard--checked': recordingMode === 'plenary' }" style="flex: 1; min-width: 240px; align-items: flex-start; flex-direction: column; gap: 4px">
						<span style="display: flex; align-items: center; gap: 8px">
							<input v-model="recordingMode" type="radio" value="plenary" />
							{{ t('organizer.shell.assemblyWizard.plenary') }}
						</span>
						<span class="cz-muted" style="font-weight: 400; font-size: 0.78rem">
							{{ t('organizer.shell.assemblyWizard.plenaryHint') }}
						</span>
					</label>
				</div>
			</div>
			<div class="cz-field">
				<label>{{ t('organizer.shell.assemblyWizard.analysis') }}</label>
				<textarea
					v-model="analysisInstructions"
					rows="2"
					:placeholder="t('organizer.shell.assemblyWizard.analysisPlaceholder')"></textarea>
				<span class="cz-muted" style="font-size: 0.78rem">
					{{ t('organizer.shell.assemblyWizard.analysisHint') }}
				</span>
			</div>
			<div class="cz-fieldgrid">
				<div class="cz-field">
					<label>{{ t('organizer.shell.assemblyWizard.language') }}</label>
					<select v-model="language">
						<option v-for="code in LANGUAGES" :key="code" :value="code">{{ t(`organizer.shell.languages.${code}`) }}</option>
					</select>
				</div>
				<div class="cz-field">
					<label>{{ t('organizer.shell.assemblyWizard.expectedParticipants') }}</label>
					<input v-model.number="expectedParticipants" type="number" min="0" max="10000" />
				</div>
				<div v-if="recordingMode !== 'plenary'" class="cz-field">
					<label>{{ t('organizer.shell.assemblyWizard.tableCount') }}</label>
					<input v-model.number="tableCount" type="number" min="1" max="200" />
					<span v-if="tableCount < 1" style="font-size: 0.78rem; color: var(--cz-orange)">
						{{ t('organizer.shell.assemblyWizard.tableCountWarning') }}
					</span>
				</div>
			</div>
			<div class="cz-row" style="justify-content: flex-end; margin-top: 8px">
				<CzButton variant="tertiary" @click="emit('cancel')">{{ t('organizer.shell.assemblyWizard.cancel') }}</CzButton>
				<CzButton variant="primary" :disabled="!basicsValid" @click="step = 2">{{ t('organizer.shell.assemblyWizard.continue') }}</CzButton>
			</div>
		</div>

		<template v-else>
			<div v-for="(round, index) in rounds" :key="index" class="cz-card">
				<div class="cz-row cz-row--spread" style="margin-bottom: 10px">
					<div class="cz-row" style="flex-wrap: nowrap">
						<span class="cz-posbadge">{{ index + 1 }}</span>
						<strong>{{ t('organizer.shell.assemblyWizard.sessionNumber', { position: index + 1 }) }}</strong>
					</div>
					<div class="cz-row" style="flex-wrap: nowrap">
						<CzButton small variant="tertiary" :icon="mdiChevronUp" :disabled="index === 0" @click="moveRound(index, -1)" />
						<CzButton small variant="tertiary" :icon="mdiChevronDown" :disabled="index === rounds.length - 1" @click="moveRound(index, 1)" />
						<CzButton small variant="tertiary" :icon="mdiDeleteOutline" :disabled="rounds.length === 1" @click="removeRound(index)" />
					</div>
				</div>
				<div class="cz-fieldgrid">
					<div class="cz-field">
						<label>{{ t('organizer.shell.assemblyWizard.sessionTitle') }}</label>
						<input v-model="round.title" type="text" />
					</div>
					<div class="cz-field" style="max-width: 180px">
						<label>{{ t('organizer.shell.assemblyWizard.duration') }}</label>
						<input v-model.number="round.duration_minutes" type="number" min="1" max="600" />
					</div>
				</div>
				<div class="cz-field" style="margin-bottom: 0">
					<label>{{ t('organizer.shell.assemblyWizard.question') }}</label>
					<textarea
						v-model="round.question"
						rows="2"
						:placeholder="t('organizer.shell.assemblyWizard.questionPlaceholder')"></textarea>
				</div>
			</div>
			<CzButton :icon="mdiPlus" @click="addRound">{{ t('organizer.shell.assemblyWizard.addSession') }}</CzButton>
			<div class="cz-row" style="justify-content: flex-end; margin-top: 20px">
				<CzButton variant="tertiary" @click="step = 1">{{ t('organizer.shell.assemblyWizard.back') }}</CzButton>
				<CzButton variant="primary" :disabled="saving || !basicsValid" @click="submit">
					{{ saving ? t('organizer.shell.assemblyWizard.creating') : t('organizer.shell.assemblyWizard.create') }}
				</CzButton>
			</div>
		</template>
	</div>
</template>
