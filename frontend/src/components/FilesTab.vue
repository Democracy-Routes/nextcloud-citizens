<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import { roundHeading } from '../labels'
import {
	mdiCellphoneRemove,
	mdiDeleteOutline,
	mdiDownloadOutline,
	mdiFolderZipOutline,
	mdiMusicNoteOutline,
	mdiPackageVariantClosed,
	mdiRefresh,
	mdiTextBoxRemoveOutline,
	mdiTextSearch,
} from '@mdi/js'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api, BASE } from '../api'
import { downloadFromApi } from '../download'
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
const { t } = useI18n()

const listing = ref<FilesListing | null>(null)
const error = ref('')
const busy = ref(false)
const downloading = ref('')
const confirmOne = ref<FileEntry | null>(null)
const confirmAll = ref(false)
const confirmTranscript = ref<FileEntry | null>(null)
const confirmRetranscribe = ref<FileEntry | null>(null)
const confirmAllTranscripts = ref(false)
const confirmPurge = ref(false)
const purgeCoverage = ref<{ devices: number; cleared: number; still_holding: number; unknown: number } | null>(null)

/** What the phones report, whether or not anyone pressed the button.
 *
 * Closing the session now asks them automatically, so there is no POST
 * response to carry this back — and a purge whose outcome nobody can see is
 * one nobody can act on when a phone turns out to still be holding something.
 * The button's own response still wins while it is fresher. */
const coverage = computed(() => {
	// Only once a purge has actually been requested. The listing always
	// carries device_audio now, and falling back to it unconditionally told
	// every open assembly "0 of 8 phones have reported clearing their copy" —
	// a privacy operation that never happened, reported as failing.
	if (purgeCoverage.value) return purgeCoverage.value
	const fromListing = listing.value?.device_audio
	return fromListing?.purge_requested_at ? fromListing : null
})

/** Ask the table phones to delete their local copies.
 *
 * Deliberately reports coverage rather than success: this reaches phones whose
 * recorder is still open, and one that was closed and carried out of the
 * building never hears about it.
 */
async function purgeDeviceAudio(): Promise<void> {
	confirmPurge.value = false
	busy.value = true
	try {
		const result = await api.purgeDeviceAudio(props.assembly.id)
		purgeCoverage.value = result
		toast(
			result.devices === 0
				? t('organizer.live.files.toast.purgeNone')
				: t('organizer.live.files.toast.purgeAsked', { count: result.devices }, result.devices),
		)
	} catch (err) {
		error.value = describeError(err).message
	} finally {
		busy.value = false
	}
}

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
		toast(t('organizer.live.files.toast.assembling', { number: entry.table_number }))
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
		toast(t('organizer.live.files.toast.retranscribing'))
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
				? t('organizer.live.files.toast.transcriptDeletedRetranscribable')
				: t('organizer.live.files.toast.transcriptDeleted'),
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
		toast(t('organizer.live.files.toast.transcriptsDeleted', { count: result.transcripts }, result.transcripts))
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
	const scale =
		total > 0
			? t('organizer.live.files.confirmAllAudio.scaleBytes', { size: bytes(total) })
			: t('organizer.live.files.confirmAllAudio.scaleAll')
	return t('organizer.live.files.confirmAllAudio.message', { scale })
})

/** Fetched rather than window.open'd: a popup blocker swallows the new tab
 * silently. The filename comes from the server, which already names these
 * after the assembly, round and table. */
async function download(path: string): Promise<void> {
	const url = `${BASE}${path}`
	downloading.value = path
	try {
		await downloadFromApi(url)
	} catch (err) {
		if (!window.open(url, '_blank')) {
			toast(describeError(err).message, 'error')
		}
	} finally {
		downloading.value = ''
	}
}

async function deleteOne(): Promise<void> {
	const entry = confirmOne.value
	confirmOne.value = null
	if (!entry) return
	busy.value = true
	try {
		const result = await api.deleteRecordingAudio(entry.recording_id)
		toast(t('organizer.live.files.toast.audioDeleted', { size: bytes(result.freed_bytes) }))
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
		toast(
			t(
				'organizer.live.files.toast.recordingsCleared',
				{ count: result.recordings, size: bytes(result.freed_bytes) },
				result.recordings,
			),
		)
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
						<h3>{{ t('organizer.live.files.header.title') }}</h3>
						<p class="cz-muted" style="margin: 4px 0 0; font-size: 0.845rem">
							{{ t('organizer.live.files.header.recordings', { count: listing.totals.recordings }, listing.totals.recordings) }} ·
							{{ bytes(listing.totals.audio_bytes) }}
							<template v-if="listing.totals.audio_deleted">
								{{ t('organizer.live.files.header.audioDeleted', { count: listing.totals.audio_deleted }) }}
							</template>
						</p>
					</div>
					<div class="cz-row" style="flex-wrap: wrap">
						<CzButton
							:icon="mdiFolderZipOutline"
							:disabled="!hasAudio"
							@click="download(`/api/v1/assemblies/${assembly.id}/audio.zip`)">
							{{ t('organizer.live.files.header.downloadAll') }}
						</CzButton>
						<CzButton
							variant="primary"
							:icon="mdiPackageVariantClosed"
							@click="download(`/api/v1/assemblies/${assembly.id}/export.zip`)">
							{{ t('organizer.live.files.header.exportFull') }}
						</CzButton>
						<CzButton
							variant="danger"
							:icon="mdiDeleteOutline"
							:disabled="busy || !hasAudio"
							@click="confirmAll = true">
							{{ t('organizer.live.files.header.deleteAllAudio') }}
						</CzButton>
						<CzButton
							variant="danger"
							:icon="mdiTextBoxRemoveOutline"
							:disabled="busy || !hasTranscripts"
							@click="confirmAllTranscripts = true">
							{{ t('organizer.live.files.header.deleteAllTranscripts') }}
						</CzButton>
						<!-- the audio on the PHONES, which no server-side deletion
						     reaches — only offered once the session is closed, since
						     until then each phone's copy is the upload safety net -->
						<CzButton
							v-if="assembly.closed_at"
							variant="danger"
							:icon="mdiCellphoneRemove"
							:disabled="busy"
							@click="confirmPurge = true">
							{{ t('organizer.live.files.header.purge') }}
						</CzButton>
					</div>
				</div>
				<!-- coverage, never "done": a phone that was closed and carried out
				     of the building simply never receives the request -->
				<p v-if="coverage" class="cz-muted" style="margin: 12px 0 0; font-size: 0.8125rem">
					<template v-if="listing?.device_audio?.purge_requested_at && !purgeCoverage">
						{{ t('organizer.live.files.coverage.askedOnClose') }}
					</template>
					<strong>{{ t('organizer.live.files.coverage.cleared', { cleared: coverage.cleared, devices: coverage.devices }) }}</strong>
					{{ t('organizer.live.files.coverage.reported') }}
					<template v-if="coverage.still_holding">
						{{ t('organizer.live.files.coverage.stillHolding', { count: coverage.still_holding }) }}
					</template>
					<template v-if="coverage.unknown">
						{{ t('organizer.live.files.coverage.unknown', { count: coverage.unknown }) }}
					</template>
					{{ t('organizer.live.files.coverage.note') }}
				</p>

				<p
					v-if="listing.totals.kept_past_retention"
					class="cz-error"
					style="margin: 12px 0 0; font-size: 0.845rem"
					role="alert">
					{{ t('organizer.live.files.keptPastRetention', { count: listing.totals.kept_past_retention }, listing.totals.kept_past_retention) }}
				</p>

				<p class="cz-muted" style="margin: 12px 0 0; font-size: 0.8125rem">
					{{ t('organizer.live.files.exportHint') }}
				</p>
			</div>

			<CzEmptyState
				v-if="listing.totals.recordings === 0"
				:icon="mdiMusicNoteOutline"
				:title="t('organizer.live.files.empty.title')"
				:hint="t('organizer.live.files.empty.hint')" />

			<div v-for="round in listing.rounds" :key="round.id">
				<div v-if="round.tables.length" class="cz-card">
					<h3 style="margin-bottom: 10px">
						{{ roundHeading(round.position, round.title) }}
					</h3>
					<table class="cz-table">
						<thead>
							<tr>
								<th>{{ t('organizer.live.files.columns.table') }}</th><th>{{ t('organizer.live.files.columns.duration') }}</th><th>{{ t('organizer.live.files.columns.size') }}</th><th>{{ t('organizer.live.files.columns.state') }}</th>
								<th>{{ t('organizer.live.files.columns.transcript') }}</th><th style="text-align: right">{{ t('organizer.live.files.columns.actions') }}</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="entry in round.tables" :key="entry.recording_id">
								<td><span class="cz-posbadge">{{ entry.table_number }}</span></td>
								<td>{{ duration(entry.duration_seconds) }}</td>
								<td>
									<template v-if="entry.audio_deleted_at">
										<span class="cz-muted">{{ t('organizer.live.files.audioDeleted') }}</span>
									</template>
									<template v-else>{{ bytes(entry.size_bytes) }}</template>
								</td>
								<td>
									<CzStatusPill :status="entry.state" />
									<CzFailureNote :state="entry.state" :error-code="entry.error_code" :job="entry.job" />
								</td>
								<td>
									<span :class="entry.has_transcript ? 'cz-ok' : 'cz-muted'">
										{{ entry.has_transcript ? '✓' : '—' }}
									</span>
									<span
										v-if="entry.transcript_source === 'live'"
										class="cz-muted"
										style="font-size: 0.72rem; margin-left: 6px"
										:title="t('organizer.live.files.liveTitle')">
										{{ t('organizer.live.files.live') }}
									</span>
								</td>
								<td style="text-align: right">
									<div class="cz-row" style="justify-content: flex-end; flex-wrap: nowrap">
										<CzButton
											small
											:icon="mdiDownloadOutline"
											:disabled="!entry.audio_available"
											@click="download(`/api/v1/recordings/${entry.recording_id}/audio`)">
											{{ t('organizer.live.files.actions.download') }}
										</CzButton>
										<CzButton
											small
											variant="tertiary"
											:icon="mdiDeleteOutline"
											:title="t('organizer.live.files.actions.deleteAudioTitle')"
											:disabled="busy || !entry.audio_available"
											@click="confirmOne = entry">
											{{ t('organizer.live.files.actions.audio') }}
										</CzButton>
										<CzButton
											v-if="entry.can_retry_assembly"
											small
											variant="tertiary"
											:icon="mdiRefresh"
											:title="t('organizer.live.files.actions.retryTitle')"
											:disabled="busy"
											@click="retryAssembly(entry)">
											{{ t('organizer.live.files.actions.retry') }}
										</CzButton>
										<CzButton
											small
											variant="tertiary"
											:icon="mdiTextSearch"
											:title="t('organizer.live.files.actions.retranscribeTitle')"
											:disabled="busy || !entry.audio_available"
											@click="confirmRetranscribe = entry">
											{{ t('organizer.live.files.actions.retranscribe') }}
										</CzButton>
										<CzButton
											small
											variant="tertiary"
											:icon="mdiTextBoxRemoveOutline"
											:title="t('organizer.live.files.actions.deleteTranscriptTitle')"
											:disabled="busy || !entry.has_transcript"
											@click="confirmTranscript = entry">
											{{ t('organizer.live.files.actions.transcript') }}
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
			:title="t('organizer.live.files.confirmRetranscribe.title')"
			:message="t('organizer.live.files.confirmRetranscribe.message', {
				number: confirmRetranscribe.table_number,
				replacing: confirmRetranscribe.transcript_source === 'live'
					? t('organizer.live.files.confirmRetranscribe.replacingLive')
					: t('organizer.live.files.confirmRetranscribe.replacingCurrent'),
			})"
			:confirm-label="t('organizer.live.files.confirmRetranscribe.confirm')"
			tone="default"
			@confirm="retranscribe"
			@cancel="confirmRetranscribe = null" />

		<CzConfirm
			v-if="confirmOne"
			:title="t('organizer.live.files.confirmDeleteAudio.title')"
			:message="t('organizer.live.files.confirmDeleteAudio.message', { number: confirmOne.table_number })"
			:confirm-label="t('organizer.live.files.confirmDeleteAudio.confirm')"
			tone="danger"
			@confirm="deleteOne"
			@cancel="confirmOne = null" />

		<CzConfirm
			v-if="confirmTranscript"
			:title="t('organizer.live.files.confirmDeleteTranscript.title')"
			:message="t('organizer.live.files.confirmDeleteTranscript.message', {
				number: confirmTranscript.table_number,
				audioNote: confirmTranscript.can_retranscribe
					? t('organizer.live.files.confirmDeleteTranscript.audioStillHere')
					: t('organizer.live.files.confirmDeleteTranscript.audioGone'),
			})"
			:confirm-label="t('organizer.live.files.confirmDeleteTranscript.confirm')"
			tone="danger"
			@confirm="deleteTranscript"
			@cancel="confirmTranscript = null" />

		<CzConfirm
			v-if="confirmPurge"
			:title="t('organizer.live.files.confirmPurge.title')"
			:message="t('organizer.live.files.confirmPurge.message')"
			:confirm-label="t('organizer.live.files.confirmPurge.confirm')"
			tone="danger"
			@confirm="purgeDeviceAudio"
			@cancel="confirmPurge = false" />

		<CzConfirm
			v-if="confirmAllTranscripts"
			:title="t('organizer.live.files.confirmAllTranscripts.title')"
			:message="t('organizer.live.files.confirmAllTranscripts.message')"
			:confirm-label="t('organizer.live.files.confirmAllTranscripts.confirm')"
			tone="danger"
			@confirm="deleteAllTranscripts"
			@cancel="confirmAllTranscripts = false" />

		<CzConfirm
			v-if="confirmAll && listing"
			:title="t('organizer.live.files.confirmAllAudio.title')"
			:message="deleteAllMessage"
			:confirm-label="t('organizer.live.files.confirmAllAudio.confirm')"
			tone="danger"
			@confirm="deleteAll"
			@cancel="confirmAll = false" />
	</div>
</template>
