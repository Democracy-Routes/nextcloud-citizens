<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import { mdiPlus, mdiDeleteOutline } from '@mdi/js'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../api'
import type { InviteGenerated, RecordingMode } from '../types'
import CzButton from './ui/CzButton.vue'

const { t } = useI18n()
// option values are the server's language codes; the names are endonyms
const LANGUAGES = ['en', 'it', 'de', 'fr', 'es'] as const

/** Create a session: the question, what it should produce, how long, how many
 * tables. One step. Adding a second session turns it into a multi-session
 * event: a name, the sessions as rounds, one report across them. Infrastructure
 * settings are not here; they belong to the instance. */
const emit = defineEmits<{ cancel: []; created: [containerId: string, invites: InviteGenerated[]] }>()

interface SessionDraft {
	title: string
	question: string
	objective: string
	duration: number
}

const error = ref('')
const saving = ref(false)

const sessions = ref<SessionDraft[]>([{ title: '', question: '', objective: '', duration: 30 }])
const tableCount = ref(1)
const recordingMode = ref<RecordingMode>('orchestrated')
const language = ref('en')

// the multi-session panel, shown from the second session on
const eventName = ref('')
const eventDescription = ref('')
const expectedParticipants = ref(50)
const analysisInstructions = ref('')
const retentionMode = ref<'default' | 'days' | 'zero'>('default')
const retentionDays = ref(30)

const multi = computed(() => sessions.value.length >= 2)

// no <form>, so min/max on the inputs only drive the spinner arrows.
// duration 0 is a real choice: no planned time, the table decides when it is
// done — not an unfilled field, so it must not block starting.
const valid = computed(
	() =>
		sessions.value.every((s) => !!s.question.trim() && s.duration >= 0) &&
		tableCount.value >= 1 &&
		(!multi.value || !!eventName.value.trim()),
)

// plenary is the whole room as one table (the server enforces this too)
watch(recordingMode, (mode) => {
	if (mode === 'plenary') tableCount.value = 1
})

function addSession(): void {
	sessions.value.push({ title: '', question: '', objective: '', duration: 30 })
}

function removeSession(index: number): void {
	sessions.value.splice(index, 1)
}

function sessionLabel(index: number): string {
	return t('organizer.shell.sessionWizard.sessionN', { n: index + 1 })
}

async function submit(): Promise<void> {
	saving.value = true
	error.value = ''
	try {
		if (!multi.value) {
			const only = sessions.value[0]
			const created = await api.createSession({
				question: only.question.trim(),
				objective: only.objective.trim() || null,
				duration_minutes: only.duration,
				table_count: tableCount.value,
				recording_mode: recordingMode.value,
				language: language.value,
			})
			emit('created', created.container_id, created.invites)
		} else {
			const created = await api.createAssembly({
				name: eventName.value.trim(),
				description: eventDescription.value,
				language: language.value,
				recording_mode: recordingMode.value,
				expected_participants: expectedParticipants.value,
				default_table_count: tableCount.value,
				analysis_instructions: analysisInstructions.value.trim(),
				rounds: sessions.value.map((s, index) => ({
					title: s.title.trim() || sessionLabel(index),
					question: s.question.trim(),
					objective: s.objective.trim() || undefined,
					duration_minutes: s.duration,
				})),
				// an organized event asks for individual consent at the table
				// before a table records; the Overview tab can relax it
				participant_consent: 'required',
				...(retentionMode.value === 'zero'
					? { zero_retention: true }
					: { zero_retention: false, audio_retention_days: retentionMode.value === 'days' ? retentionDays.value : null }),
			})
			emit('created', created.id, created.invites)
		}
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err)
	} finally {
		saving.value = false
	}
}
</script>

<template>
	<div class="cz-page" style="max-width: 720px">
		<h2>{{ multi ? t('organizer.shell.sessionWizard.titleMulti') : t('organizer.shell.sessionWizard.title') }}</h2>
		<p class="cz-muted" style="margin: 4px 0 16px">
			{{ t('organizer.shell.sessionWizard.intro') }}
		</p>

		<div v-if="error" class="cz-error">{{ error }}</div>

		<div class="cz-card">
			<div v-if="multi" class="cz-field">
				<label for="cz-session-title">{{ t('organizer.shell.sessionWizard.sessionTitle') }}</label>
				<input id="cz-session-title" v-model="sessions[0].title" type="text" maxlength="200" :placeholder="sessionLabel(0)" />
			</div>
			<div class="cz-field">
				<label for="cz-session-question">{{ t('organizer.shell.sessionWizard.question') }}</label>
				<textarea
					id="cz-session-question"
					v-model="sessions[0].question"
					rows="2"
					maxlength="2000"
					:placeholder="t('organizer.shell.sessionWizard.questionPlaceholder')"></textarea>
			</div>
			<div class="cz-field">
				<label for="cz-session-objective">{{ t('organizer.shell.sessionWizard.objective') }}</label>
				<textarea
					id="cz-session-objective"
					v-model="sessions[0].objective"
					rows="2"
					maxlength="2000"
					:placeholder="t('organizer.shell.sessionWizard.objectivePlaceholder')"></textarea>
				<span class="cz-muted" style="font-size: 0.78rem">
					{{ t('organizer.shell.sessionWizard.objectiveHint') }}
				</span>
			</div>
			<div class="cz-field">
				<label>{{ t('organizer.shell.sessionWizard.recordingMode') }}</label>
				<div class="cz-row">
					<label class="cz-radiocard" :class="{ 'cz-radiocard--checked': recordingMode === 'orchestrated' }" style="flex: 1; min-width: 200px; align-items: flex-start; flex-direction: column; gap: 4px">
						<span style="display: flex; align-items: center; gap: 8px">
							<input v-model="recordingMode" type="radio" value="orchestrated" />
							{{ t('organizer.shell.sessionWizard.orchestrated') }}
						</span>
						<span class="cz-muted" style="font-weight: 400; font-size: 0.78rem">
							{{ t('organizer.shell.sessionWizard.orchestratedHint') }}
						</span>
					</label>
					<label class="cz-radiocard" :class="{ 'cz-radiocard--checked': recordingMode === 'independent' }" style="flex: 1; min-width: 200px; align-items: flex-start; flex-direction: column; gap: 4px">
						<span style="display: flex; align-items: center; gap: 8px">
							<input v-model="recordingMode" type="radio" value="independent" />
							{{ t('organizer.shell.sessionWizard.independent') }}
						</span>
						<span class="cz-muted" style="font-weight: 400; font-size: 0.78rem">
							{{ t('organizer.shell.sessionWizard.independentHint') }}
						</span>
					</label>
					<label class="cz-radiocard" :class="{ 'cz-radiocard--checked': recordingMode === 'plenary' }" style="flex: 1; min-width: 200px; align-items: flex-start; flex-direction: column; gap: 4px">
						<span style="display: flex; align-items: center; gap: 8px">
							<input v-model="recordingMode" type="radio" value="plenary" />
							{{ t('organizer.shell.sessionWizard.plenary') }}
						</span>
						<span class="cz-muted" style="font-weight: 400; font-size: 0.78rem">
							{{ t('organizer.shell.sessionWizard.plenaryHint') }}
						</span>
					</label>
				</div>
			</div>
			<div class="cz-fieldgrid">
				<div class="cz-field" style="max-width: 180px">
					<label for="cz-session-duration">{{ t('organizer.shell.sessionWizard.duration') }}</label>
					<input id="cz-session-duration" v-model.number="sessions[0].duration" type="number" min="0" max="600" />
					<span v-if="sessions[0].duration === 0" class="cz-muted" style="font-size: 0.78rem">
						{{ t('organizer.setup.overview.rounds.noPlannedTime') }}
					</span>
				</div>
				<div v-if="recordingMode !== 'plenary'" class="cz-field" style="max-width: 180px">
					<label for="cz-session-tables">{{ t('organizer.shell.sessionWizard.tables') }}</label>
					<input id="cz-session-tables" v-model.number="tableCount" type="number" min="1" max="200" />
				</div>
				<div class="cz-field" style="max-width: 180px">
					<label for="cz-session-language">{{ t('organizer.shell.sessionWizard.language') }}</label>
					<select id="cz-session-language" v-model="language">
						<option v-for="code in LANGUAGES" :key="code" :value="code">{{ t(`organizer.shell.languages.${code}`) }}</option>
					</select>
				</div>
			</div>
			<CzButton :icon="mdiPlus" data-test="wizard-add-session" @click="addSession">{{ t('organizer.shell.sessionWizard.addSession') }}</CzButton>
		</div>

		<div v-for="(extra, offset) in sessions.slice(1)" :key="offset" class="cz-card">
			<div class="cz-row cz-row--spread" style="margin-bottom: 10px">
				<strong>{{ sessionLabel(offset + 1) }}</strong>
				<CzButton small variant="tertiary" :icon="mdiDeleteOutline" data-test="wizard-remove-session" :label="t('organizer.shell.sessionWizard.removeSession')" @click="removeSession(offset + 1)" />
			</div>
			<div class="cz-fieldgrid">
				<div class="cz-field">
					<label :for="`cz-session-title-${offset + 1}`">{{ t('organizer.shell.sessionWizard.sessionTitle') }}</label>
					<input :id="`cz-session-title-${offset + 1}`" v-model="extra.title" type="text" maxlength="200" :placeholder="sessionLabel(offset + 1)" />
				</div>
				<div class="cz-field" style="max-width: 180px">
					<label :for="`cz-session-duration-${offset + 1}`">{{ t('organizer.shell.sessionWizard.duration') }}</label>
					<input :id="`cz-session-duration-${offset + 1}`" v-model.number="extra.duration" type="number" min="0" max="600" />
					<span v-if="extra.duration === 0" class="cz-muted" style="font-size: 0.78rem">
						{{ t('organizer.setup.overview.rounds.noPlannedTime') }}
					</span>
				</div>
			</div>
			<div class="cz-field">
				<label :for="`cz-session-question-${offset + 1}`">{{ t('organizer.shell.sessionWizard.question') }}</label>
				<textarea
					:id="`cz-session-question-${offset + 1}`"
					v-model="extra.question"
					rows="2"
					maxlength="2000"
					:placeholder="t('organizer.shell.sessionWizard.questionPlaceholder')"></textarea>
			</div>
			<div class="cz-field" style="margin-bottom: 0">
				<label :for="`cz-session-objective-${offset + 1}`">{{ t('organizer.shell.sessionWizard.objective') }}</label>
				<textarea
					:id="`cz-session-objective-${offset + 1}`"
					v-model="extra.objective"
					rows="2"
					maxlength="2000"
					:placeholder="t('organizer.shell.sessionWizard.objectivePlaceholder')"></textarea>
			</div>
		</div>

		<div v-if="multi" class="cz-card" data-test="wizard-multi">
			<h3 style="margin-top: 0">{{ t('organizer.shell.sessionWizard.multiTitle') }}</h3>
			<p class="cz-muted" style="margin: 4px 0 12px; font-size: 0.875rem">
				{{ t('organizer.shell.sessionWizard.multiHint') }}
			</p>
			<div class="cz-field">
				<label for="cz-event-name">{{ t('organizer.shell.sessionWizard.name') }}</label>
				<input id="cz-event-name" v-model="eventName" type="text" maxlength="200" :placeholder="t('organizer.shell.sessionWizard.namePlaceholder')" />
			</div>
			<div class="cz-field">
				<label for="cz-event-description">{{ t('organizer.shell.sessionWizard.description') }}</label>
				<textarea id="cz-event-description" v-model="eventDescription" rows="2"></textarea>
			</div>
			<div class="cz-fieldgrid">
				<div class="cz-field" style="max-width: 220px">
					<label for="cz-event-participants">{{ t('organizer.shell.sessionWizard.participants') }}</label>
					<input id="cz-event-participants" v-model.number="expectedParticipants" type="number" min="0" max="10000" />
				</div>
			</div>
			<div class="cz-field">
				<label for="cz-event-analysis">{{ t('organizer.shell.sessionWizard.analysis') }}</label>
				<textarea
					id="cz-event-analysis"
					v-model="analysisInstructions"
					rows="2"
					:placeholder="t('organizer.shell.sessionWizard.analysisPlaceholder')"></textarea>
				<span class="cz-muted" style="font-size: 0.78rem">
					{{ t('organizer.shell.sessionWizard.analysisHint') }}
				</span>
			</div>
			<div class="cz-field" data-test="retention" style="margin-bottom: 0">
				<label>{{ t('organizer.setup.overview.retention.label') }}</label>
				<label style="display: flex; align-items: center; gap: 8px; cursor: pointer">
					<input v-model="retentionMode" type="radio" value="default" />
					{{ t('organizer.setup.overview.retention.default') }}
				</label>
				<label style="display: flex; align-items: center; gap: 8px; cursor: pointer">
					<input v-model="retentionMode" type="radio" value="days" />
					{{ t('organizer.setup.overview.retention.days', { days: retentionDays }) }}
				</label>
				<input
					v-if="retentionMode === 'days'"
					v-model.number="retentionDays"
					type="number"
					min="1"
					max="3650"
					style="max-width: 120px; margin-left: 28px" />
				<label style="display: flex; align-items: center; gap: 8px; cursor: pointer">
					<input v-model="retentionMode" type="radio" value="zero" />
					{{ t('organizer.setup.overview.retention.zero') }}
				</label>
				<span class="cz-muted" style="font-size: 0.78rem">
					{{ t('organizer.setup.overview.retention.zeroHelp') }}
				</span>
			</div>
		</div>

		<div class="cz-row" style="justify-content: flex-end; margin-top: 12px">
			<CzButton variant="tertiary" @click="emit('cancel')">{{ t('organizer.shell.sessionWizard.cancel') }}</CzButton>
			<CzButton variant="primary" :disabled="saving || !valid" @click="submit">
				<template v-if="multi">{{ saving ? t('organizer.shell.sessionWizard.creating') : t('organizer.shell.sessionWizard.create') }}</template>
				<template v-else>{{ saving ? t('organizer.shell.sessionWizard.starting') : t('organizer.shell.sessionWizard.start') }}</template>
			</CzButton>
		</div>
	</div>
</template>
