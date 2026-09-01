<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import {
	mdiAccountGroup,
	mdiAccountPlus,
	mdiDeleteOutline,
	mdiFileDelimitedOutline,
	mdiPlaylistPlus,
} from '@mdi/js'
import { onMounted, ref } from 'vue'
import { api } from '../api'
import { describeError, type UiError } from '../errors'
import { useAsyncAction } from '../composables/useAsyncAction'
import type { Participant } from '../types'
import CzButton from './ui/CzButton.vue'
import CzError from './ui/CzError.vue'
import CzConfirm from './ui/CzConfirm.vue'
import CzEmptyState from './ui/CzEmptyState.vue'
import CzSkeleton from './ui/CzSkeleton.vue'
import { toast } from './ui/toast'

const props = defineProps<{ assemblyId: string }>()
const emit = defineEmits<{ changed: [] }>()

const participants = ref<Participant[]>([])
const loaded = ref(false)
const error = ref('')
const newLabel = ref('')
const newName = ref('')
const csvText = ref('')
const showCsv = ref(false)
const removeTarget = ref<Participant | null>(null)
const loadError = ref<UiError | null>(null)

async function reload(): Promise<void> {
	try {
		participants.value = await api.listParticipants(props.assemblyId)
		loadError.value = null
	} catch (err) {
		loadError.value = describeError(err)
	} finally {
		loaded.value = true
	}
}

onMounted(reload)

const { busy, error: actionError, run: runGuarded } = useAsyncAction()

async function run(action: () => Promise<unknown>): Promise<void> {
	// pressing Enter twice used to add the participant twice, and a
	// double-clicked CSV import added fifty people twice
	if (await runGuarded(action)) {
		await reload()
		emit('changed')
	}
}

const addOne = () =>
	run(async () => {
		await api.addParticipants(props.assemblyId, [
			{ label: newLabel.value.trim(), name: newName.value.trim() },
		])
		newLabel.value = ''
		newName.value = ''
	})

const importCsv = () =>
	run(async () => {
		const imported = await api.importCsv(props.assemblyId, csvText.value)
		csvText.value = ''
		showCsv.value = false
		toast(`${imported.length} participants imported`)
	})

function prefill(): void {
	const start = participants.value.length + 1
	csvText.value =
		'label,name,email\n' +
		Array.from({ length: 50 }, (_, i) => `P${String(start + i).padStart(3, '0')},,`).join('\n')
	showCsv.value = true
}

const remove = () =>
	run(async () => {
		if (removeTarget.value) await api.deleteParticipant(removeTarget.value.id)
		removeTarget.value = null
	})

function initials(participant: Participant): string {
	if (participant.name) {
		return participant.name
			.split(/\s+/)
			.slice(0, 2)
			.map((part) => part[0]?.toUpperCase() ?? '')
			.join('')
	}
	return participant.label.slice(0, 3)
}
</script>

<template>
	<div>
		<CzError v-if="loadError" :error="loadError" @retry="reload" />
		<CzError v-else-if="actionError" :error="actionError" />
		<div v-else-if="error" class="cz-error">{{ error }}</div>
		<CzSkeleton v-if="!loaded" :rows="4" />

		<template v-else>
			<div class="cz-card">
				<div class="cz-row">
					<input v-model="newLabel" type="text" placeholder="Label (e.g. P001)" style="width: 140px" @keyup.enter="addOne" />
					<input v-model="newName" type="text" placeholder="Name (optional)" style="width: 200px" @keyup.enter="addOne" />
					<CzButton variant="primary" small :icon="mdiAccountPlus" :disabled="busy || !newLabel.trim()" @click="addOne">Add</CzButton>
					<span style="flex: 1"></span>
					<CzButton small :icon="mdiFileDelimitedOutline" @click="showCsv = !showCsv">CSV import</CzButton>
					<CzButton small :icon="mdiPlaylistPlus" :disabled="busy" @click="prefill">Prefill 50 anonymous</CzButton>
				</div>
				<div v-if="showCsv" style="margin-top: 14px">
					<p class="cz-muted" style="font-size: 13px">
						Header <code>label,name,email</code> — names and emails are optional. Anonymous labels are enough.
					</p>
					<textarea v-model="csvText" rows="8" style="width: 100%; font-family: ui-monospace, monospace"></textarea>
					<div class="cz-row" style="margin-top: 8px; justify-content: flex-end">
						<CzButton variant="primary" small :disabled="busy || !csvText.trim()" @click="importCsv">Import participants</CzButton>
					</div>
				</div>
			</div>

			<CzEmptyState
				v-if="participants.length === 0"
				:icon="mdiAccountGroup"
				title="No participants yet"
				hint="Participants can stay fully anonymous — use “Prefill 50 anonymous” to generate P001…P050 in one click." />

			<template v-else>
				<h3 style="margin: 18px 0 10px">{{ participants.length }} participants</h3>
				<table class="cz-table">
					<thead>
						<tr><th style="width: 40px"></th><th>Label</th><th>Name</th><th>Email</th><th style="width: 60px"></th></tr>
					</thead>
					<tbody>
						<tr v-for="participant in participants" :key="participant.id">
							<td><span class="cz-avatar">{{ initials(participant) }}</span></td>
							<td><strong>{{ participant.label }}</strong></td>
							<td>{{ participant.name || '—' }}</td>
							<td class="cz-muted">{{ participant.email || '—' }}</td>
							<td style="text-align: right">
								<CzButton small variant="tertiary" :icon="mdiDeleteOutline" title="Remove" :disabled="busy" @click="removeTarget = participant" />
							</td>
						</tr>
					</tbody>
				</table>
			</template>
		</template>

		<CzConfirm
			v-if="removeTarget"
			title="Remove participant?"
			:message="`${removeTarget.label}${removeTarget.name ? ' (' + removeTarget.name + ')' : ''} will be removed from this assembly.`"
			confirm-label="Remove"
			@confirm="remove"
			@cancel="removeTarget = null" />
	</div>
</template>
