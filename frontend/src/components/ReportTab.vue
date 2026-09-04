<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import {
	mdiCellphoneLink,
	mdiCheckCircleOutline,
	mdiCodeJson,
	mdiDownloadOutline,
	mdiFileDocumentOutline,
	mdiFilePdfBox,
	mdiLockOpenVariantOutline,
	mdiRefresh,
} from '@mdi/js'
import { computed, ref, watch } from 'vue'
import { api, BASE } from '../api'
import { downloadBlob, downloadFromApi } from '../download'
import { SLOW_MS } from '../composables/intervals'
import { usePolling } from '../composables/usePolling'
import { TYPE_LABELS, groupByType, roundHeading } from '../labels'
import type { AssemblyDetail, ReportData } from '../types'
import CzFreshness from './ui/CzFreshness.vue'
import CzButton from './ui/CzButton.vue'
import CzConfirm from './ui/CzConfirm.vue'
import CzEmptyState from './ui/CzEmptyState.vue'
import CzSkeleton from './ui/CzSkeleton.vue'
import { toast } from './ui/toast'

const props = defineProps<{ assembly: AssemblyDetail }>()
const emit = defineEmits<{ changed: [] }>()

const report = ref<ReportData | null>(null)
const error = ref('')
const includeDrafts = ref(false)
const confirmPublish = ref(false)
// unpublishing removes the report from every table phone that is reading it
const confirmUnpublish = ref(false)
// reopening undoes "final", which participants have already been shown
const confirmReopen = ref(false)
const confirmClose = ref(false)
const publishing = ref(false)
const refreshing = ref(false)
const downloading = ref<'' | 'md' | 'pdf'>('')
const closing = ref(false)

const isFinal = computed(() => !!report.value?.is_final)
const progress = computed(() => report.value?.progress)

function closedDate(): string {
	const raw = report.value?.closed_at
	return raw ? new Date(raw).toLocaleDateString() : ''
}

async function closeSession(): Promise<void> {
	confirmClose.value = false
	closing.value = true
	try {
		await api.closeSession(props.assembly.id)
		toast('Session closed — the final report is ready')
		await reload()
		emit('changed')
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err)
	} finally {
		closing.value = false
	}
}

async function reopenSession(): Promise<void> {
	closing.value = true
	try {
		await api.reopenSession(props.assembly.id)
		toast('Session reopened — tables can record again')
		await reload()
		emit('changed')
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err)
	} finally {
		closing.value = false
	}
}

async function togglePublish(): Promise<void> {
	confirmPublish.value = false
	publishing.value = true
	try {
		if (report.value?.published_at) {
			await api.unpublishReport(props.assembly.id)
			toast('Report is no longer visible on table phones')
		} else {
			await api.publishReport(props.assembly.id)
			toast('Report published — table phones can now view and download it')
		}
		await reload()
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err)
	} finally {
		publishing.value = false
	}
}

/** Re-freeze the published version from the current content.
 *
 * Closing snapshots the report once, and reopening deliberately leaves that
 * snapshot alone so phones keep showing exactly what they showed at closing.
 * The consequence was a dead end: approve a finding after reopening, close
 * again, and the phones still read the old version with nothing in the UI able
 * to update it. The endpoint existed and had never been given a button. */
async function refreshFinal(): Promise<void> {
	refreshing.value = true
	try {
		await api.refreshFinalReport(props.assembly.id)
		toast('The published version now matches the current report')
		await reload()
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err)
	} finally {
		refreshing.value = false
	}
}

// shared deliberation-report vocabulary + grouped rendering order

async function reload(): Promise<void> {
	try {
		report.value = await api.assemblyReport(props.assembly.id, includeDrafts.value)
		error.value = ''
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err)
	}
}

// slower than the live view: a report changes when a person approves a
// finding, not on its own — but it must not stay stale for the whole event
const polling = usePolling(reload, { intervalMs: SLOW_MS })
watch(includeDrafts, reload)

/** Fetched rather than window.open'd: a popup blocker swallows the new tab
 * silently, and the organizer is left thinking the button is broken. */
async function downloadReport(extension: 'md' | 'pdf'): Promise<void> {
	const url = `${BASE}/api/v1/assemblies/${props.assembly.id}/report.${extension}?include_drafts=${includeDrafts.value}`
	downloading.value = extension
	try {
		await downloadFromApi(url)
	} catch {
		if (!window.open(url, '_blank')) {
			toast('The report could not be downloaded — check the pop-up blocker', 'error')
		}
	} finally {
		downloading.value = ''
	}
}

function downloadJson(): void {
	if (!report.value) return
	// downloadBlob, not a hand-rolled anchor: this one revoked the object URL
	// on the next line and never put the anchor in the document, so Firefox
	// and Safari cancelled the download before it started and said nothing.
	downloadBlob(
		new Blob([JSON.stringify(report.value, null, 2)], { type: 'application/json' }),
		`${slug()}-report.json`,
	)
}

const slug = () => props.assembly.name.slice(0, 40).replace(/ /g, '-')

const hasContent = () =>
	!!report.value &&
	report.value.rounds.some(
		(r) => r.cross_table.length > 0 || !!r.summary || r.tables.some((t) => t.findings.length > 0 || !!t.summary),
	)
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

		<div v-if="report" class="cz-card cz-nextstep" style="margin-bottom: 16px">
			<div>
				<template v-if="isFinal">
					<strong>Final report · closed {{ closedDate() }}</strong>
					<span class="cz-muted" style="display: block; font-size: 0.8125rem; margin-top: 2px">
						The session is closed: tables can no longer record, and this is the
						definitive report. Participants keep reading this version even if you
						reopen — approve more findings and press Update to push them.
					</span>
				</template>
				<template v-else-if="progress?.complete">
					<strong style="color: var(--cz-green)">All {{ progress.tables_expected }} tables have finished.</strong>
					<span class="cz-muted" style="display: block; font-size: 0.8125rem; margin-top: 2px">
						Close the session to create the final report and enable the downloads.
					</span>
				</template>
				<template v-else>
					<strong>Interim report — {{ progress?.tables_complete ?? 0 }} of
						{{ progress?.tables_expected ?? 0 }} tables have completed all rounds</strong>
					<span class="cz-muted" style="display: block; font-size: 0.8125rem; margin-top: 2px">
						This is a preview of an assembly still in progress. Closing the session
						creates the final report and enables the downloads — you can reopen later.
					</span>
				</template>
			</div>
			<CzButton
				v-if="!isFinal"
				variant="primary"
				:icon="mdiCheckCircleOutline"
				:disabled="closing"
				@click="confirmClose = true">
				Close session &amp; create final report
			</CzButton>
			<div v-else class="cz-row" style="flex-wrap: nowrap">
				<CzButton
					variant="tertiary"
					:icon="mdiRefresh"
					:disabled="refreshing || closing"
					@click="refreshFinal">
					{{ refreshing ? 'Updating…' : 'Update the published version' }}
				</CzButton>
				<CzButton
					variant="tertiary"
					:icon="mdiLockOpenVariantOutline"
					:disabled="closing"
					@click="confirmReopen = true">
					Reopen session
				</CzButton>
			</div>
		</div>

		<div class="cz-row cz-row--spread" style="margin-bottom: 16px">
			<label style="display: flex; align-items: center; gap: 8px; cursor: pointer">
				<input v-model="includeDrafts" type="checkbox" />
				Include unreviewed drafts (clearly marked)
			</label>
			<div class="cz-row">
				<CzButton
					small
					:icon="mdiFilePdfBox"
					:disabled="!isFinal || !!downloading"
					@click="downloadReport('pdf')">
					{{ downloading === 'pdf' ? 'Preparing…' : 'PDF' }}
				</CzButton>
				<CzButton
					small
					:icon="mdiDownloadOutline"
					:disabled="!isFinal || !!downloading"
					@click="downloadReport('md')">
					{{ downloading === 'md' ? 'Preparing…' : 'Markdown' }}
				</CzButton>
				<CzButton small :icon="mdiCodeJson" :disabled="!isFinal" @click="downloadJson">JSON</CzButton>
			</div>
		</div>
		<p v-if="!isFinal" class="cz-muted" style="margin: -8px 0 16px; font-size: 0.8125rem; text-align: right">
			Downloads become available once the session is closed.
		</p>

		<div v-if="report" class="cz-card" style="margin-bottom: 16px">
			<div class="cz-row cz-row--spread">
				<div style="flex: 1; min-width: 240px">
					<h3>
						<template v-if="report.published_at">Published to table phones</template>
						<template v-else>Not yet published to table phones</template>
					</h3>
					<p class="cz-muted" style="margin: 4px 0 0; font-size: 0.845rem">
						<template v-if="report.published_at">
							Recording phones can view this report and download the PDF
							(approved findings and AI summaries only — drafts stay private).
						</template>
						<template v-else>
							Publishing lets the recording phones view this report and download
							the PDF. Only approved findings and AI summaries are shared.
						</template>
					</p>
				</div>
				<CzButton
					small
					:variant="report.published_at ? 'tertiary' : 'primary'"
					:icon="mdiCellphoneLink"
					:disabled="publishing"
					@click="report.published_at ? (confirmUnpublish = true) : (confirmPublish = true)">
					{{ report.published_at ? 'Unpublish' : 'Publish report to tables' }}
				</CzButton>
			</div>
		</div>

		<CzSkeleton v-if="!report && !error" :rows="4" />

		<CzEmptyState
			v-else-if="report && !hasContent()"
			:icon="mdiFileDocumentOutline"
			title="Nothing to report yet"
			:hint="includeDrafts
				? 'No findings exist yet — record tables and run the analysis first.'
				: 'No approved findings yet. Approve findings in the Analysis tab, or include drafts to preview.'" />

		<template v-else-if="report">
			<div class="cz-card">
				<h2 style="font-size: 1.31rem">{{ report.assembly.name }} — Assembly Report</h2>
				<p v-if="report.assembly.description" class="cz-muted" style="margin-top: 6px">
					{{ report.assembly.description }}
				</p>
				<p class="cz-muted" style="font-size: 0.845rem; margin: 8px 0 0">
					{{ report.assembly.participants }} participants ·
					{{ report.assembly.tables }} tables ·
					{{ report.assembly.language.toUpperCase() }}
				</p>
				<p style="font-size: 0.875rem; margin-top: 12px">{{ report.method }}</p>
			</div>

			<template v-for="round in report.rounds" :key="round.position">
				<div
					v-if="round.cross_table.length || round.summary || round.tables.some((t) => t.findings.length || t.summary)"
					class="cz-card">
					<h3>{{ roundHeading(round.position, round.title) }}</h3>
					<p v-if="round.question" class="cz-muted" style="font-style: italic; margin: 4px 0 14px">
						“{{ round.question }}”
					</p>
					<p v-if="round.summary" style="font-size: 0.905rem; font-style: italic; margin-bottom: 14px">
						<span class="cz-muted" style="font-style: normal; font-size: 0.75rem; display: block">AI SUMMARY</span>
						{{ round.summary }}
					</p>

					<template v-if="round.cross_table.length">
						<h4 style="font-size: 0.875rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--cz-text-muted); margin: 12px 0 8px">
							Across all tables
						</h4>
						<template v-for="group in groupByType(round.cross_table)" :key="group.type">
							<h5
								style="font-size: 0.845rem; font-weight: 700; margin: 10px 0 8px"
								:style="{ color: group.type === 'disagreement' ? 'var(--cz-amber)' : 'var(--cz-primary)' }">
								{{ group.label }}
							</h5>
							<div v-for="finding in group.findings" :key="finding.id" style="margin-bottom: 14px">
								<strong>
									{{ finding.title }}
									<span v-if="finding.is_draft" class="cz-pill cz-pill--amber" style="text-transform: none">DRAFT — not reviewed</span>
								</strong>
								<p v-if="finding.mentioned_table_count" class="cz-muted" style="font-size: 0.8125rem; margin: 2px 0">
									Mentioned at {{ finding.mentioned_table_count }} table(s)
								</p>
								<p style="margin: 4px 0; font-size: 0.905rem">{{ finding.summary }}</p>
								<blockquote
									v-for="(evidence, index) in finding.evidence.slice(0, 3)"
									:key="index"
									style="margin: 6px 0; padding: 4px 12px; border-left: 3px solid var(--cz-border); font-size: 0.845rem; color: var(--cz-text-muted)">
									[{{ evidence.timestamp }}] {{ evidence.speaker || 'Speaker' }}: “{{ evidence.text }}”
								</blockquote>
									<p
										v-if="!finding.evidence.length && finding.evidence_removed"
										class="cz-muted"
										style="font-size: 0.8125rem; font-style: italic; margin: 4px 0">
										Evidence removed with the transcript
									</p>
							</div>
						</template>
					</template>

					<template v-for="table in round.tables" :key="table.table_number">
						<template v-if="table.findings.length || table.summary">
							<h4 style="font-size: 0.875rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--cz-text-muted); margin: 16px 0 8px">
								Table {{ table.table_number }}
							</h4>
							<p v-if="table.summary" style="font-size: 0.875rem; font-style: italic; margin: 0 0 10px">
								<span class="cz-muted" style="font-style: normal; font-size: 0.75rem; display: block">AI SUMMARY</span>
								{{ table.summary }}
							</p>
							<div v-for="finding in table.findings" :key="finding.id" style="margin-bottom: 14px">
								<strong>
									{{ TYPE_LABELS[finding.type] ?? finding.type }}: {{ finding.title }}
									<span v-if="finding.is_draft" class="cz-pill cz-pill--amber" style="text-transform: none">DRAFT — not reviewed</span>
								</strong>
								<p style="margin: 4px 0; font-size: 0.905rem">{{ finding.summary }}</p>
								<blockquote
									v-for="(evidence, index) in finding.evidence.slice(0, 3)"
									:key="index"
									style="margin: 6px 0; padding: 4px 12px; border-left: 3px solid var(--cz-border); font-size: 0.845rem; color: var(--cz-text-muted)">
									[{{ evidence.timestamp }}] {{ evidence.speaker || 'Speaker' }}: “{{ evidence.text }}”
								</blockquote>
									<p
										v-if="!finding.evidence.length && finding.evidence_removed"
										class="cz-muted"
										style="font-size: 0.8125rem; font-style: italic; margin: 4px 0">
										Evidence removed with the transcript
									</p>
							</div>
						</template>
					</template>
				</div>
			</template>

			<p class="cz-muted" style="font-size: 0.8125rem; font-style: italic">
				{{ report.methodology_note }}
			</p>
		</template>

		<CzConfirm
			v-if="confirmClose && report"
			title="Close the session and create the final report?"
			:message="(progress?.tables_missing?.length
				? `Tables ${progress.tables_missing.join(', ')} never recorded — they will not appear in the final report. `
				: '') + 'Tables can no longer record after closing, and the report becomes final. You can reopen the session later if a late table needs to record.'"
			confirm-label="Close session"
			:danger="false"
			@confirm="closeSession"
			@cancel="confirmClose = false" />

		<CzConfirm
			v-if="confirmUnpublish"
			title="Stop sharing the report with the tables?"
			message="Every table phone currently reading the report loses access to it immediately. You can publish it again at any time."
			confirm-label="Unpublish"
			tone="danger"
			@confirm="confirmUnpublish = false; togglePublish()"
			@cancel="confirmUnpublish = false" />

		<CzConfirm
			v-if="confirmReopen"
			title="Reopen this session?"
			message="Tables can record again and the report stops being final. Participants keep reading the version that was frozen when the session closed, until you close it again."
			confirm-label="Reopen session"
			@confirm="confirmReopen = false; reopenSession()"
			@cancel="confirmReopen = false" />

		<CzConfirm
			v-if="confirmPublish"
			title="Publish report to table phones?"
			message="Every table's recording phone will be able to view this report and download the PDF. Only approved findings and AI summaries are included — unreviewed drafts stay private. You can unpublish at any time."
			confirm-label="Publish"
			@confirm="togglePublish"
			@cancel="confirmPublish = false" />
	</div>
</template>
