<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import {
	mdiDeleteOutline,
	mdiDownloadOutline,
	mdiFolderZipOutline,
	mdiMusicNoteOutline,
	mdiRefresh,
	mdiPackageVariantClosed,
	mdiTextBoxRemoveOutline,
	mdiTextSearch,
} from '@mdi/js'
import { computed, ref } from 'vue'
import { api, BASE } from '../api'
import { describeError } from '../errors'
import { bytes, duration } from '../format'
import { BACKGROUND_MS } from '../composables/intervals'
import { usePolling } from '../composables/usePolling'
import type { AssemblyDetail, FileEntry, FilesListing } from '../types'
import CzButton from './ui/CzButton.vue'
import CzConfirm from './ui/CzConfirm.vue'
import CzEmptyState from './ui/CzEmptyState.vue'
import CzFailureNote from './ui/CzFailureNote.vue'
import CzFreshness from './ui/CzFreshness.vue'
import CzSkeleton from './ui/CzSkeleton.vue'
import CzStatusPill from './ui/CzStatusPill.vue'
import { toast } from './ui/toast'

const props = defineProps<{ assembly: AssemblyDetail }>()

const listing = ref<FilesListing | null>(null)
const error = ref('')
const busy = ref(false)
const confirmOne = ref<FileEntry | null>(null)
const confirmAll = ref(false)
const confirmTranscript = ref<FileEntry | null>(null)
const confirmRetranscribe = ref<FileEntry | null>(null)
const confirmAllTranscripts = ref(false)

async function reload(): Promise<void> {
	try {
		listing.value = await api.listFiles(props.assembly.id)
		error.value = ''
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err)
	}
}

/** Refresh while any recording is still being worked on.
 *
 * This tab never refreshed at all, so a re-transcription started here showed
 * TRANSCRIBING until the facilitator left the tab and came back — the work
 * finishing was invisible.
 */
const TERMINAL = new Set([
	'REVIEWED',
	'READY_FOR_REVIEW',
	'AUDIO_INVALID',
	'TRANSCRIPTION_FAILED',
	'ANALYSIS_FAILED',
	'UPLOAD_INCOMPLETE',
])

const working = computed(() =>
	(listing.value?.rounds ?? []).some((round) =>
		round.tables.some((table) => !TERMINAL.has(table.state)),
	),
)

const polling = usePolling(
	async () => {
		// Always load the first time. Gating the whole poll on `working` meant
		// the tab never loaded at all, because nothing is "working" while the
		// listing is still null.
		if (listing.value === null || working.value) await reload()
	},
	{ intervalMs: BACKGROUND_MS },
)

const hasAudio = computed(() =>
	(listing.value?.rounds ?? []).some((round) => round.tables.some((t) => t.audio_available)),
)

const hasTranscripts = computed(() =>
	(listing.value?.rounds ?? []).some((round) => round.tables.some((t) => t.has_transcript)),
)

/** The way out of a recording stuck after a failed assembly.
 *
 * The endpoint existed with nothing calling it, so a table wedged by a full
 * disk still had no route back once space was freed. */
async function retryAssembly(entry: FileEntry): Promise<void> {
	busy.value = true
	try {
		await api.retryAssembly(entry.recording_id)
		toast(`Assembling table ${entry.table_number} again`)
		await reload()
	} catch (err) {
		error.value = describeError(err).message
	} finally {
		busy.value = false
	}
}

async function retranscribe(): Promise<void> {
	const entry = confirmRetranscribe.value
	confirmRetranscribe.value = null
	if (!entry) return
	busy.value = true
	try {
		await api.requestTranscription(entry.recording_id)
		toast('Transcribing again from the stored audio — this can take a few minutes')
		await reload()
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err)
	} finally {
		busy.value = false
	}
}

async function deleteTranscript(): Promise<void> {
	const entry = confirmTranscript.value
	confirmTranscript.value = null
	if (!entry) return
	busy.value = true
	try {
		const result = await api.deleteRecordingTranscript(entry.recording_id)
		toast(
			result.retranscribable
				? 'Transcript deleted — this recording can be transcribed again'
				: 'Transcript deleted',
		)
		await reload()
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err)
	} finally {
		busy.value = false
	}
}

async function deleteAllTranscripts(): Promise<void> {
	confirmAllTranscripts.value = false
	busy.value = true
	try {
		const result = await api.deleteAssemblyTranscripts(props.assembly.id)
		toast(`${result.transcripts} transcripts deleted`)
		await reload()
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err)
	} finally {
		busy.value = false
	}
}

/** bytes() renders an em dash for zero, which produced the sentence
 * "All — of recorded audio will be permanently deleted". */
const deleteAllMessage = computed(() => {
	const total = listing.value?.totals.audio_bytes ?? 0
	const scale = total > 0 ? `All ${bytes(total)} of recorded audio` : 'All recorded audio'
	return `${scale} will be permanently deleted and cannot be recovered. Transcripts, findings and the report are kept. Download or export first if you need a copy.`
})

function download(path: string): void {
	window.open(`${BASE}${path}`, '_blank')
}

async function deleteOne(): Promise<void> {
	const entry = confirmOne.value
	confirmOne.value = null
	if (!entry) return
	busy.value = true
	try {
		const result = await api.deleteRecordingAudio(entry.recording_id)
		toast(`Audio deleted — ${bytes(result.freed_bytes)} freed`)
		await reload()
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err)
	} finally {
		busy.value = false
	}
}

async function deleteAll(): Promise<void> {
	confirmAll.value = false
	busy.value = true
	try {
		const result = await api.deleteAssemblyAudio(props.assembly.id)
		toast(`${result.recordings} recordings cleared — ${bytes(result.freed_bytes)} freed`)
		await reload()
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err)
	} finally {
		busy.value = false
	}
}
</script>

<template>
	<div>
		<div class="cz-row cz-row--spread" style="margin-bottom: 10px">
			<CzFreshness
				:last-success-at="polling.lastSuccessAt.value"
				:consecutive-failures="polling.consecutiveFailures.value"
				@refresh="reload" />
		</div>

		<div v-if="error" class="cz-error">{{ error }}</div>

		<CzSkeleton v-if="!listing && !error" :rows="4" />

		<template v-else-if="listing">
			<div class="cz-card">
				<div class="cz-row cz-row--spread">
					<div style="flex: 1; min-width: 240px">
						<h3>Audio files &amp; exports</h3>
						<p class="cz-muted" style="margin: 4px 0 0; font-size: 0.845rem">
							{{ listing.totals.recordings }} recordings ·
							{{ bytes(listing.totals.audio_bytes) }}
							<template v-if="listing.totals.audio_deleted">
								· {{ listing.totals.audio_deleted }} with audio deleted
							</template>
						</p>
					</div>
					<div class="cz-row" style="flex-wrap: wrap">
						<CzButton
							:icon="mdiFolderZipOutline"
							:disabled="!hasAudio"
							@click="download(`/api/v1/assemblies/${assembly.id}/audio.zip`)">
							Download all audio
						</CzButton>
						<CzButton
							variant="primary"
							:icon="mdiPackageVariantClosed"
							@click="download(`/api/v1/assemblies/${assembly.id}/export.zip`)">
							Export full session
						</CzButton>
						<CzButton
							variant="danger"
							:icon="mdiDeleteOutline"
							:disabled="busy || !hasAudio"
							@click="confirmAll = true">
							Delete all audio
						</CzButton>
						<CzButton
							variant="danger"
							:icon="mdiTextBoxRemoveOutline"
							:disabled="busy || !hasTranscripts"
							@click="confirmAllTranscripts = true">
							Delete all transcripts
						</CzButton>
					</div>
				</div>
				<p class="cz-muted" style="margin: 12px 0 0; font-size: 0.8125rem">
					The full session export bundles metadata, audio, transcripts and the report —
					enough to move this assembly to another server. Deleting audio keeps transcripts,
					findings and the report.
				</p>
			</div>

			<CzEmptyState
				v-if="listing.totals.recordings === 0"
				:icon="mdiMusicNoteOutline"
				title="No recordings yet"
				hint="Audio files appear here as soon as the tables record and synchronize." />

			<div v-for="round in listing.rounds" :key="round.id">
				<div v-if="round.tables.length" class="cz-card">
					<h3 style="margin-bottom: 10px">
						Round {{ round.position }} — {{ round.title || 'Untitled' }}
					</h3>
					<table class="cz-table">
						<thead>
							<tr>
								<th>Table</th><th>Duration</th><th>Size</th><th>State</th>
								<th>Transcript</th><th style="text-align: right">Actions</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="entry in round.tables" :key="entry.recording_id">
								<td><span class="cz-posbadge">{{ entry.table_number }}</span></td>
								<td>{{ duration(entry.duration_seconds) }}</td>
								<td>
									<template v-if="entry.audio_deleted_at">
										<span class="cz-muted">audio deleted</span>
									</template>
									<template v-else>{{ bytes(entry.size_bytes) }}</template>
								</td>
								<td>
									<CzStatusPill :status="entry.state" />
									<CzFailureNote :state="entry.state" :error-code="entry.error_code" />
								</td>
								<td>
									<span :class="entry.has_transcript ? 'cz-ok' : 'cz-muted'">
										{{ entry.has_transcript ? '✓' : '—' }}
									</span>
									<span
										v-if="entry.transcript_source === 'live'"
										class="cz-muted"
										style="font-size: 0.72rem; margin-left: 6px"
										title="From the live captions, not a transcription of the finished audio">
										live
									</span>
								</td>
								<td style="text-align: right">
									<div class="cz-row" style="justify-content: flex-end; flex-wrap: nowrap">
										<CzButton
											small
											:icon="mdiDownloadOutline"
											:disabled="!entry.audio_available"
											@click="download(`/api/v1/recordings/${entry.recording_id}/audio`)">
											Download
										</CzButton>
										<CzButton
											small
											variant="tertiary"
											:icon="mdiDeleteOutline"
											title="Delete audio"
											:disabled="busy || !entry.audio_available"
											@click="confirmOne = entry">
											Audio
										</CzButton>
										<CzButton
											v-if="entry.can_retry_assembly"
											small
											variant="tertiary"
											:icon="mdiRefresh"
											title="Try assembling the audio again"
											:disabled="busy"
											@click="retryAssembly(entry)">
											Retry
										</CzButton>
										<CzButton
											small
											variant="tertiary"
											:icon="mdiTextSearch"
											title="Transcribe again from the stored audio"
											:disabled="busy || !entry.audio_available"
											@click="confirmRetranscribe = entry">
											Re-transcribe
										</CzButton>
										<CzButton
											small
											variant="tertiary"
											:icon="mdiTextBoxRemoveOutline"
											title="Delete transcript"
											:disabled="busy || !entry.has_transcript"
											@click="confirmTranscript = entry">
											Transcript
										</CzButton>
									</div>
								</td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>
		</template>

		<CzConfirm
			v-if="confirmRetranscribe"
			title="Transcribe this table again?"
			:message="`Table ${confirmRetranscribe.table_number} will be transcribed again from its stored audio${confirmRetranscribe.transcript_source === 'live' ? ', replacing the transcript taken from the live captions' : ', replacing the current transcript'}. Quotes inside existing findings refer to the old text, so they are marked as removed, and the analysis runs again. The audio is not touched.`"
			confirm-label="Transcribe again"
			tone="default"
			@confirm="retranscribe"
			@cancel="confirmRetranscribe = null" />

		<CzConfirm
			v-if="confirmOne"
			title="Delete this table's audio?"
			:message="`The audio of table ${confirmOne.table_number} will be permanently deleted and cannot be recovered. Its transcript, findings and the report are kept — but the recording can never be transcribed again.`"
			confirm-label="Delete audio"
			tone="danger"
			@confirm="deleteOne"
			@cancel="confirmOne = null" />

		<CzConfirm
			v-if="confirmTranscript"
			title="Delete this table's transcript?"
			:message="`The verbatim text of table ${confirmTranscript.table_number} will be permanently erased — including the quotes shown inside findings and in the published report. The findings and AI summaries stay. ${confirmTranscript.can_retranscribe ? 'The audio is still here, so this recording can be transcribed again.' : 'Its audio is already deleted, so the transcript cannot be recreated.'}`"
			confirm-label="Delete transcript"
			tone="danger"
			@confirm="deleteTranscript"
			@cancel="confirmTranscript = null" />

		<CzConfirm
			v-if="confirmAllTranscripts"
			title="Delete all transcripts of this session?"
			message="Every table's verbatim text will be permanently erased, including the quotes inside findings and in the published report. Findings and AI summaries stay. Tables whose audio is still here can be transcribed again."
			confirm-label="Delete all transcripts"
			tone="danger"
			@confirm="deleteAllTranscripts"
			@cancel="confirmAllTranscripts = false" />

		<CzConfirm
			v-if="confirmAll && listing"
			title="Delete all audio of this session?"
			:message="deleteAllMessage"
			confirm-label="Delete all audio"
			tone="danger"
			@confirm="deleteAll"
			@cancel="confirmAll = false" />
	</div>
</template>
