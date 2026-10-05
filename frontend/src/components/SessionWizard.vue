<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from '../api'
import type { InviteGenerated, RecordingMode } from '../types'
import CzButton from './ui/CzButton.vue'

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
		<h2>Start a Session</h2>
		<p class="cz-muted" style="margin: 4px 0 16px">
			One discussion, at one or more tables, once. Add tables and recorder phones while it runs; if
			you later want a second session, the Session becomes an Assembly.
		</p>

		<div v-if="error" class="cz-error">{{ error }}</div>

		<div class="cz-card">
			<div class="cz-field">
				<label for="cz-session-question">Question</label>
				<textarea
					id="cz-session-question"
					v-model="question"
					rows="2"
					maxlength="2000"
					placeholder="How should local mobility improve?"></textarea>
			</div>
			<div class="cz-field">
				<label for="cz-session-objective">Objective (optional)</label>
				<textarea
					id="cz-session-objective"
					v-model="objective"
					rows="2"
					maxlength="2000"
					placeholder="Produce three concrete proposals."></textarea>
				<span class="cz-muted" style="font-size: 0.78rem">
					What the discussion should produce, as distinct from what it is about.
				</span>
			</div>
			<div class="cz-field">
				<label>How the tables record</label>
				<div class="cz-row">
					<label class="cz-radiocard" :class="{ 'cz-radiocard--checked': recordingMode === 'orchestrated' }" style="flex: 1; min-width: 200px; align-items: flex-start; flex-direction: column; gap: 4px">
						<span style="display: flex; align-items: center; gap: 8px">
							<input v-model="recordingMode" type="radio" value="orchestrated" />
							Together
						</span>
						<span class="cz-muted" style="font-weight: 400; font-size: 0.78rem">
							You start and end the Session for every table at once.
						</span>
					</label>
					<label class="cz-radiocard" :class="{ 'cz-radiocard--checked': recordingMode === 'independent' }" style="flex: 1; min-width: 200px; align-items: flex-start; flex-direction: column; gap: 4px">
						<span style="display: flex; align-items: center; gap: 8px">
							<input v-model="recordingMode" type="radio" value="independent" />
							Each table on its own
						</span>
						<span class="cz-muted" style="font-weight: 400; font-size: 0.78rem">
							Every table starts and stops when it is ready — even on different days.
						</span>
					</label>
					<label class="cz-radiocard" :class="{ 'cz-radiocard--checked': recordingMode === 'plenary' }" style="flex: 1; min-width: 200px; align-items: flex-start; flex-direction: column; gap: 4px">
						<span style="display: flex; align-items: center; gap: 8px">
							<input v-model="recordingMode" type="radio" value="plenary" />
							One room, many phones
						</span>
						<span class="cz-muted" style="font-weight: 400; font-size: 0.78rem">
							The whole room is one discussion; any number of phones record it together.
						</span>
					</label>
				</div>
			</div>
			<div class="cz-fieldgrid">
				<div class="cz-field" style="max-width: 180px">
					<label for="cz-session-duration">Duration (minutes)</label>
					<input id="cz-session-duration" v-model.number="duration" type="number" min="1" max="600" />
				</div>
				<div v-if="recordingMode !== 'plenary'" class="cz-field" style="max-width: 180px">
					<label for="cz-session-tables">Tables</label>
					<input id="cz-session-tables" v-model.number="tableCount" type="number" min="1" max="200" />
				</div>
				<div class="cz-field" style="max-width: 180px">
					<label for="cz-session-language">Language</label>
					<select id="cz-session-language" v-model="language">
						<option value="en">English</option>
						<option value="it">Italiano</option>
						<option value="de">Deutsch</option>
						<option value="fr">Français</option>
						<option value="es">Español</option>
					</select>
				</div>
			</div>
			<div class="cz-row" style="justify-content: flex-end; margin-top: 8px">
				<CzButton variant="tertiary" @click="emit('cancel')">Cancel</CzButton>
				<CzButton variant="primary" :disabled="saving || !valid" @click="submit">
					{{ saving ? 'Starting…' : 'Start Session' }}
				</CzButton>
			</div>
		</div>
	</div>
</template>
