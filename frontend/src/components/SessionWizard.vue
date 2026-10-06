<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../api'
import type { InviteGenerated, RecordingMode } from '../types'
import CzButton from './ui/CzButton.vue'

const { t } = useI18n()
// option values are the server's language codes; the names are endonyms
const LANGUAGES = ['en', 'it', 'de', 'fr', 'es'] as const

/** Start a Session: the question, what it should produce, how long, how many
 * tables. One step — there is no assembly to describe first. Infrastructure
 * settings are not here; they belong to the instance. */
const emit = defineEmits<{ cancel: []; created: [containerId: string, invites: InviteGenerated[]] }>()

const error = ref('')
const saving = ref(false)

const question = ref('')
const objective = ref('')
const duration = ref(30)
const tableCount = ref(1)
const recordingMode = ref<RecordingMode>('orchestrated')
const language = ref('en')

// no <form>, so min/max on the inputs only drive the spinner arrows
const valid = computed(() => !!question.value.trim() && tableCount.value >= 1 && duration.value >= 1)

// plenary is the whole room as one table (the server enforces this too)
watch(recordingMode, (mode) => {
	if (mode === 'plenary') tableCount.value = 1
})

async function submit(): Promise<void> {
	saving.value = true
	error.value = ''
	try {
		const created = await api.createSession({
			question: question.value.trim(),
			objective: objective.value.trim() || null,
			duration_minutes: duration.value,
			table_count: tableCount.value,
			recording_mode: recordingMode.value,
			language: language.value,
		})
		emit('created', created.container_id, created.invites)
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err)
	} finally {
		saving.value = false
	}
}
</script>

<template>
	<div class="cz-page" style="max-width: 720px">
		<h2>{{ t('organizer.shell.sessionWizard.title') }}</h2>
		<p class="cz-muted" style="margin: 4px 0 16px">
			{{ t('organizer.shell.sessionWizard.intro') }}
		</p>

		<div v-if="error" class="cz-error">{{ error }}</div>

		<div class="cz-card">
			<div class="cz-field">
				<label for="cz-session-question">{{ t('organizer.shell.sessionWizard.question') }}</label>
				<textarea
					id="cz-session-question"
					v-model="question"
					rows="2"
					maxlength="2000"
					:placeholder="t('organizer.shell.sessionWizard.questionPlaceholder')"></textarea>
			</div>
			<div class="cz-field">
				<label for="cz-session-objective">{{ t('organizer.shell.sessionWizard.objective') }}</label>
				<textarea
					id="cz-session-objective"
					v-model="objective"
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
					<input id="cz-session-duration" v-model.number="duration" type="number" min="1" max="600" />
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
			<div class="cz-row" style="justify-content: flex-end; margin-top: 8px">
				<CzButton variant="tertiary" @click="emit('cancel')">{{ t('organizer.shell.sessionWizard.cancel') }}</CzButton>
				<CzButton variant="primary" :disabled="saving || !valid" @click="submit">
					{{ saving ? t('organizer.shell.sessionWizard.starting') : t('organizer.shell.sessionWizard.start') }}
				</CzButton>
			</div>
		</div>
	</div>
</template>
