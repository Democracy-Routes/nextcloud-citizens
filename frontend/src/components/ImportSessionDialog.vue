<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
/**
 * Import a session: an export.zip made by this app, here or on another server,
 * becomes an assembly. The file goes up in parts (upload.ts), then one call
 * asks the server to build the assembly from it. Errors stay in the dialog so
 * the organizer can fix the merges and try again without choosing the file anew.
 */
import { computed, ref, useId } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../api'
import type { ImportResult } from '../types'
import { uploadFile } from '../upload'
import { useFocusTrap } from '../composables/useFocusTrap'
import CzButton from './ui/CzButton.vue'

const { t } = useI18n()
const emit = defineEmits<{ close: []; openAssembly: [id: string] }>()

interface MergeRow {
	from: number | null
	into: number | null
}

const dialog = ref<HTMLElement | null>(null)
const titleId = useId()
const file = ref<File | null>(null)
const name = ref('')
const merges = ref<MergeRow[]>([])
const busy = ref(false)
const progress = ref(0)
const importing = ref(false)
const error = ref('')
const result = ref<ImportResult | null>(null)

useFocusTrap(dialog, () => {
	if (!busy.value) emit('close')
})

const sizeLabel = computed(() => {
	const bytes = file.value?.size ?? 0
	return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`
})

function onFile(event: Event): void {
	const input = event.target as HTMLInputElement
	file.value = input.files?.[0] ?? null
	error.value = ''
}

function addMerge(): void {
	merges.value.push({ from: null, into: null })
}

function removeMerge(index: number): void {
	merges.value.splice(index, 1)
}

async function submit(): Promise<void> {
	if (!file.value || busy.value) return
	busy.value = true
	error.value = ''
	progress.value = 0
	importing.value = false
	try {
		const uploaded = await uploadFile(file.value, 'session_export', (fraction) => {
			progress.value = fraction
		})
		importing.value = true
		const merge_tables = merges.value
			.filter((row) => row.from != null && row.into != null)
			.map((row) => ({ from: Number(row.from), into: Number(row.into) }))
		result.value = await api.importSession({
			upload_id: uploaded.upload_id,
			...(name.value.trim() ? { name: name.value.trim() } : {}),
			...(merge_tables.length ? { merge_tables } : {}),
		})
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err)
	} finally {
		busy.value = false
		importing.value = false
	}
}
</script>

<template>
	<div class="cz-modal-mask" @click.self="!busy && emit('close')">
		<div ref="dialog" class="cz-modal" role="dialog" aria-modal="true" :aria-labelledby="titleId" style="max-width: 560px">
			<div class="cz-modal__head">
				<h3 :id="titleId">{{ t('organizer.shell.importDialog.title') }}</h3>
			</div>

			<div v-if="result" data-test="import-result">
				<p><strong>{{ result.name }}</strong></p>
				<ul>
					<li>{{ t('organizer.shell.importDialog.rounds', { count: result.rounds }, result.rounds) }}</li>
					<li>{{ t('organizer.shell.importDialog.tables', { count: result.tables }, result.tables) }}</li>
					<li>{{ t('organizer.shell.importDialog.recordings', { count: result.recordings }, result.recordings) }}</li>
					<li>{{ t('organizer.shell.importDialog.transcripts', { count: result.transcripts }, result.transcripts) }}</li>
					<li>{{ t('organizer.shell.importDialog.audioFiles', { count: result.audio_files }, result.audio_files) }}</li>
				</ul>
				<p class="cz-muted">
					{{ result.analysis_queued ? t('organizer.shell.importDialog.analysisQueued') : t('organizer.shell.importDialog.analysisNotQueued') }}
				</p>
				<div v-if="result.skipped.length">
					<strong>{{ t('organizer.shell.importDialog.skipped') }}</strong>
					<ul data-test="import-skipped">
						<li v-for="line in result.skipped" :key="line">{{ line }}</li>
					</ul>
				</div>
				<div class="cz-modal__actions">
					<CzButton variant="tertiary" @click="emit('close')">{{ t('organizer.shell.importDialog.close') }}</CzButton>
					<CzButton variant="primary" data-test="import-open-assembly" @click="emit('openAssembly', result.assembly_id)">
						{{ t('organizer.shell.importDialog.openAssembly') }}
					</CzButton>
				</div>
			</div>

			<form v-else @submit.prevent="submit">
				<div class="cz-field">
					<label :for="titleId + '-file'">{{ t('organizer.shell.importDialog.file') }}</label>
					<input :id="titleId + '-file'" type="file" accept=".zip,application/zip" data-test="import-file" :disabled="busy" @change="onFile" />
					<div v-if="file" class="cz-muted" data-test="import-file-info">{{ file.name }} · {{ sizeLabel }}</div>
				</div>

				<div class="cz-field">
					<label :for="titleId + '-name'">{{ t('organizer.shell.importDialog.name') }}</label>
					<input :id="titleId + '-name'" v-model="name" type="text" data-test="import-name" :disabled="busy" />
					<div class="cz-muted">{{ t('organizer.shell.importDialog.nameHint') }}</div>
				</div>

				<div class="cz-field">
					<label>{{ t('organizer.shell.importDialog.merges') }}</label>
					<div class="cz-muted">{{ t('organizer.shell.importDialog.mergesHint') }}</div>
					<div
						v-for="(row, index) in merges"
						:key="index"
						data-test="import-merge-row"
						style="display: flex; gap: 8px; align-items: center; margin-top: 8px; flex-wrap: wrap">
						<input v-model.number="row.from" type="number" min="1" style="width: 90px" :aria-label="t('organizer.shell.importDialog.mergeFrom')" :placeholder="t('organizer.shell.importDialog.mergeFrom')" :disabled="busy" />
						<input v-model.number="row.into" type="number" min="1" style="width: 110px" :aria-label="t('organizer.shell.importDialog.mergeInto')" :placeholder="t('organizer.shell.importDialog.mergeInto')" :disabled="busy" />
						<CzButton variant="tertiary" small data-test="import-merge-remove" :disabled="busy" @click="removeMerge(index)">
							{{ t('organizer.shell.importDialog.mergeRemove') }}
						</CzButton>
					</div>
					<div style="margin-top: 8px">
						<CzButton small data-test="import-merge-add" :disabled="busy" @click="addMerge">{{ t('organizer.shell.importDialog.mergeAdd') }}</CzButton>
					</div>
				</div>

				<div v-if="busy" data-test="import-progress" role="status">
					<template v-if="importing">{{ t('organizer.shell.importDialog.importing') }}</template>
					<template v-else>
						<progress :value="progress" max="1" style="width: 100%"></progress>
						<div class="cz-muted">{{ t('organizer.shell.importDialog.uploading', { percent: Math.round(progress * 100) }) }}</div>
					</template>
				</div>
				<div v-if="error" class="cz-error" data-test="import-error">{{ error }}</div>

				<div class="cz-modal__actions">
					<CzButton variant="tertiary" :disabled="busy" @click="emit('close')">{{ t('organizer.shell.importDialog.close') }}</CzButton>
					<CzButton variant="primary" data-test="import-submit" :disabled="!file || busy" @click="submit">
						{{ t('organizer.shell.importDialog.submit') }}
					</CzButton>
				</div>
			</form>
		</div>
	</div>
</template>
