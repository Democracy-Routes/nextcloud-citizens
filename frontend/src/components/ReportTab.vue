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
import { useI18n } from 'vue-i18n'
import { api, BASE } from '../api'
import { downloadBlob, downloadFromApi } from '../download'
import { SLOW_MS } from '../composables/intervals'
import { usePolling } from '../composables/usePolling'
import { groupByType, roundHeading, typeLabel } from '../labels'
import type { AssemblyDetail, ReportData } from '../types'
import CzFreshness from './ui/CzFreshness.vue'
import CzButton from './ui/CzButton.vue'
import CzConfirm from './ui/CzConfirm.vue'
import CzEmptyState from './ui/CzEmptyState.vue'
import CzSkeleton from './ui/CzSkeleton.vue'
import { toast } from './ui/toast'

const props = defineProps<{ assembly: AssemblyDetail }>()
const emit = defineEmits<{ changed: [] }>()
const { t } = useI18n()

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
		toast(t('organizer.results.report.toast.closed'))
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
		toast(t('organizer.results.report.toast.reopened'))
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
			toast(t('organizer.results.report.toast.unpublished'))
		} else {
			await api.publishReport(props.assembly.id)
			toast(t('organizer.results.report.toast.published'))
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
const synthesising = ref(false)
async function generateSynthesis(): Promise<void> {
	synthesising.value = true
	try {
		await api.generateSynthesis(props.assembly.id)
		toast(t('organizer.results.report.toast.synthesisQueued'))
		// the job runs in the background: look again a little later
		window.setTimeout(() => void reload(), 20_000)
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err)
	} finally {
		window.setTimeout(() => (synthesising.value = false), 20_000)
	}
}

async function refreshFinal(): Promise<void> {
	refreshing.value = true
	try {
		await api.refreshFinalReport(props.assembly.id)
		toast(t('organizer.results.report.toast.refreshed'))
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
			toast(t('organizer.results.report.toast.downloadFailed'), 'error')
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
					<strong>{{ t('organizer.results.report.finalTitle', { date: closedDate() }) }}</strong>
					<span class="cz-muted" style="display: block; font-size: 0.8125rem; margin-top: 2px">
						{{ t('organizer.results.report.finalHint') }}
					</span>
				</template>
				<template v-else-if="progress?.complete">
					<strong style="color: var(--cz-green)">{{ t('organizer.results.report.allDoneTitle', { count: progress.tables_expected }, progress.tables_expected) }}</strong>
					<span class="cz-muted" style="display: block; font-size: 0.8125rem; margin-top: 2px">
						{{ t('organizer.results.report.allDoneHint') }}
					</span>
				</template>
				<template v-else>
					<strong>{{ t('organizer.results.report.interimTitle', { complete: progress?.tables_complete ?? 0, expected: progress?.tables_expected ?? 0 }) }}</strong>
					<span class="cz-muted" style="display: block; font-size: 0.8125rem; margin-top: 2px">
						{{ t('organizer.results.report.interimHint') }}
					</span>
				</template>
			</div>
			<CzButton
				v-if="!isFinal"
				variant="primary"
				:icon="mdiCheckCircleOutline"
				:disabled="closing"
				@click="confirmClose = true">
				{{ t('organizer.results.report.close') }}
			</CzButton>
			<div v-else class="cz-row" style="flex-wrap: nowrap">
				<CzButton
					variant="tertiary"
					:icon="mdiRefresh"
					:disabled="refreshing || closing"
					@click="refreshFinal">
					{{ refreshing ? t('organizer.results.report.updating') : t('organizer.results.report.updatePublished') }}
				</CzButton>
				<CzButton
					variant="tertiary"
					:icon="mdiLockOpenVariantOutline"
					:disabled="closing"
					@click="confirmReopen = true">
					{{ t('organizer.results.report.reopen') }}
				</CzButton>
			</div>
		</div>

		<!-- how the discussion developed across sessions: made by itself at
		     closing; here for an organizer who wants it earlier or again -->
		<div v-if="report && report.rounds.length >= 2" class="cz-card" style="margin-bottom: 16px" data-test="synthesis-card">
			<div class="cz-row cz-row--spread">
				<div style="flex: 1; min-width: 240px">
					<h3>{{ t('organizer.results.report.synthesis.title') }}</h3>
					<p class="cz-muted" style="margin: 4px 0 0; font-size: 0.845rem">
						<template v-if="report.synthesis">
							{{ t('organizer.results.report.synthesis.haveLead') }}
							<template v-if="report.synthesis.generated_at"> · {{ report.synthesis.generated_at.slice(0, 16).replace('T', ' ') }}</template>.
							{{ t('organizer.results.report.synthesis.haveTail') }}
						</template>
						<template v-else>
							{{ t('organizer.results.report.synthesis.none') }}
						</template>
					</p>
				</div>
				<CzButton small variant="secondary" :icon="mdiRefresh" :disabled="synthesising" data-test="synthesis" @click="generateSynthesis">
					{{ synthesising ? t('organizer.results.report.synthesis.queued') : report.synthesis ? t('organizer.results.report.synthesis.again') : t('organizer.results.report.synthesis.generate') }}
				</CzButton>
			</div>
			<template v-if="report.synthesis">
				<p style="font-size: 0.9375rem; line-height: 1.55; margin: 12px 0 0">{{ report.synthesis.narrative }}</p>
				<div v-for="stage in report.synthesis.stages" :key="stage.title" style="margin-top: 10px">
					<strong style="font-size: 0.875rem">{{ stage.title }}</strong>
					<p style="font-size: 0.875rem; margin: 2px 0 0">{{ stage.summary }}</p>
				</div>
				<p v-if="report.synthesis.carried_forward.length" class="cz-muted" style="font-size: 0.8125rem; margin: 10px 0 4px">
					{{ t('organizer.results.report.synthesis.carried') }}
				</p>
				<ul v-if="report.synthesis.carried_forward.length" style="margin: 0; padding-left: 18px; font-size: 0.875rem">
					<li v-for="item in report.synthesis.carried_forward" :key="item">{{ item }}</li>
				</ul>
			</template>
		</div>

		<div class="cz-row cz-row--spread" style="margin-bottom: 16px">
			<label style="display: flex; align-items: center; gap: 8px; cursor: pointer">
				<input v-model="includeDrafts" type="checkbox" />
				{{ t('organizer.results.report.includeDrafts') }}
			</label>
			<div class="cz-row">
				<CzButton
					small
					:icon="mdiFilePdfBox"
					:disabled="!isFinal || !!downloading"
					@click="downloadReport('pdf')">
					{{ downloading === 'pdf' ? t('organizer.results.report.preparing') : t('organizer.results.report.pdf') }}
				</CzButton>
				<CzButton
					small
					:icon="mdiDownloadOutline"
					:disabled="!isFinal || !!downloading"
					@click="downloadReport('md')">
					{{ downloading === 'md' ? t('organizer.results.report.preparing') : t('organizer.results.report.markdown') }}
				</CzButton>
				<CzButton small :icon="mdiCodeJson" :disabled="!isFinal" @click="downloadJson">{{ t('organizer.results.report.json') }}</CzButton>
			</div>
		</div>
		<p v-if="!isFinal" class="cz-muted" style="margin: -8px 0 16px; font-size: 0.8125rem; text-align: right">
			{{ t('organizer.results.report.downloadsLocked') }}
		</p>

		<div v-if="report" class="cz-card" style="margin-bottom: 16px">
			<div class="cz-row cz-row--spread">
				<div style="flex: 1; min-width: 240px">
					<h3>
						<template v-if="report.published_at">{{ t('organizer.results.report.publishedTitle') }}</template>
						<template v-else>{{ t('organizer.results.report.unpublishedTitle') }}</template>
					</h3>
					<p class="cz-muted" style="margin: 4px 0 0; font-size: 0.845rem">
						<template v-if="report.published_at">
							{{ t('organizer.results.report.publishedHint') }}
						</template>
						<template v-else>
							{{ t('organizer.results.report.unpublishedHint') }}
						</template>
					</p>
				</div>
				<CzButton
					small
					:variant="report.published_at ? 'tertiary' : 'primary'"
					:icon="mdiCellphoneLink"
					:disabled="publishing"
					@click="report.published_at ? (confirmUnpublish = true) : (confirmPublish = true)">
					{{ report.published_at ? t('organizer.results.report.unpublish') : t('organizer.results.report.publish') }}
				</CzButton>
			</div>
		</div>

		<CzSkeleton v-if="!report && !error" :rows="4" />

		<CzEmptyState
			v-else-if="report && !hasContent()"
			:icon="mdiFileDocumentOutline"
			:title="t('organizer.results.report.emptyTitle')"
			:hint="includeDrafts
				? t('organizer.results.report.emptyHintDrafts')
				: t('organizer.results.report.emptyHintApproved')" />

		<template v-else-if="report">
			<div class="cz-card">
				<h2 style="font-size: 1.31rem">{{ t('organizer.results.report.assemblyReport', { name: report.assembly.name }) }}</h2>
				<p v-if="report.assembly.description" class="cz-muted" style="margin-top: 6px">
					{{ report.assembly.description }}
				</p>
				<p class="cz-muted" style="font-size: 0.845rem; margin: 8px 0 0">
					{{ t('organizer.results.report.participants', { count: report.assembly.participants }, report.assembly.participants) }} ·
					{{ t('organizer.results.report.tables', { count: report.assembly.tables }, report.assembly.tables) }} ·
					{{ report.assembly.language.toUpperCase() }}
				</p>
				<p style="font-size: 0.875rem; margin-top: 12px">{{ report.method }}</p>
			</div>

			<template v-for="round in report.rounds" :key="round.position">
				<div
					v-if="round.cross_table.length || round.summary || round.tables.some((t) => t.findings.length || t.summary)"
					class="cz-card">
					<h3>{{ round.heading ?? roundHeading(round.position, round.title) }}</h3>
					<p v-if="round.question" class="cz-muted" style="font-style: italic; margin: 4px 0 14px">
						“{{ round.question }}”
					</p>
					<p v-if="round.summary" style="font-size: 0.905rem; font-style: italic; margin-bottom: 14px">
						<span class="cz-muted" style="font-style: normal; font-size: 0.75rem; display: block">{{ t('organizer.results.report.aiSummary') }}</span>
						{{ round.summary }}
					</p>

					<template v-if="round.cross_table.length">
						<h4 style="font-size: 0.875rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--cz-text-muted); margin: 12px 0 8px">
							{{ t('organizer.results.report.acrossTables') }}
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
									<span v-if="finding.is_draft" class="cz-pill cz-pill--amber" style="text-transform: none">{{ t('organizer.results.report.draftPill') }}</span>
								</strong>
								<p v-if="finding.mentioned_table_count" class="cz-muted" style="font-size: 0.8125rem; margin: 2px 0">
									{{ t('organizer.results.report.mentionedAt', { count: finding.mentioned_table_count }, finding.mentioned_table_count) }}
								</p>
								<p style="margin: 4px 0; font-size: 0.905rem">{{ finding.summary }}</p>
								<blockquote
									v-for="(evidence, index) in finding.evidence.slice(0, 3)"
									:key="index"
									style="margin: 6px 0; padding: 4px 12px; border-left: 3px solid var(--cz-border); font-size: 0.845rem; color: var(--cz-text-muted)">
									[{{ evidence.timestamp }}] {{ evidence.speaker || t('organizer.results.report.speaker') }}: “{{ evidence.text }}”
								</blockquote>
									<p
										v-if="!finding.evidence.length && finding.evidence_removed"
										class="cz-muted"
										style="font-size: 0.8125rem; font-style: italic; margin: 4px 0">
										{{ t('organizer.results.report.evidenceRemoved') }}
									</p>
							</div>
						</template>
					</template>

					<template v-for="table in round.tables" :key="table.table_number">
						<template v-if="table.findings.length || table.summary">
							<h4 style="font-size: 0.875rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--cz-text-muted); margin: 16px 0 8px">
								{{ t('organizer.results.report.table', { number: table.table_number }) }}
							</h4>
							<!-- participants' word on the summary (0.7): counts, and the
							     notes of those who flagged something missing -->
							<p v-if="table.validations" class="cz-validation" data-test="validations">
								<span class="cz-validation__ok">{{ t('organizer.results.report.looksRight', { count: table.validations.looks_right }, table.validations.looks_right) }}</span>
								<span v-if="table.validations.missing" class="cz-validation__flag">
									{{ t('organizer.results.report.flaggedMissing', { count: table.validations.missing }, table.validations.missing) }}
								</span>
							</p>
							<ul v-if="table.validations?.notes?.length" class="cz-validation__notes">
								<li v-for="(note, index) in table.validations.notes" :key="index">“{{ note }}”</li>
							</ul>
							<p v-if="table.summary" style="font-size: 0.875rem; font-style: italic; margin: 0 0 10px">
								<span class="cz-muted" style="font-style: normal; font-size: 0.75rem; display: block">{{ t('organizer.results.report.aiSummary') }}</span>
								{{ table.summary }}
							</p>
							<div v-for="finding in table.findings" :key="finding.id" style="margin-bottom: 14px">
								<strong>
									{{ finding.type_label ?? typeLabel(finding.type) }}: {{ finding.title }}
									<span v-if="finding.is_draft" class="cz-pill cz-pill--amber" style="text-transform: none">{{ t('organizer.results.report.draftPill') }}</span>
								</strong>
								<p style="margin: 4px 0; font-size: 0.905rem">{{ finding.summary }}</p>
								<blockquote
									v-for="(evidence, index) in finding.evidence.slice(0, 3)"
									:key="index"
									style="margin: 6px 0; padding: 4px 12px; border-left: 3px solid var(--cz-border); font-size: 0.845rem; color: var(--cz-text-muted)">
									[{{ evidence.timestamp }}] {{ evidence.speaker || t('organizer.results.report.speaker') }}: “{{ evidence.text }}”
								</blockquote>
									<p
										v-if="!finding.evidence.length && finding.evidence_removed"
										class="cz-muted"
										style="font-size: 0.8125rem; font-style: italic; margin: 4px 0">
										{{ t('organizer.results.report.evidenceRemoved') }}
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
			:title="t('organizer.results.report.confirmClose.title')"
			:message="(progress?.tables_missing?.length
				? t('organizer.results.report.confirmClose.missingTables', { tables: progress.tables_missing.join(', ') })
				: '') + t('organizer.results.report.confirmClose.body')"
			:confirm-label="t('organizer.results.report.confirmClose.confirm')"
			:danger="false"
			@confirm="closeSession"
			@cancel="confirmClose = false" />

		<CzConfirm
			v-if="confirmUnpublish"
			:title="t('organizer.results.report.confirmUnpublish.title')"
			:message="t('organizer.results.report.confirmUnpublish.message')"
			:confirm-label="t('organizer.results.report.confirmUnpublish.confirm')"
			tone="danger"
			@confirm="confirmUnpublish = false; togglePublish()"
			@cancel="confirmUnpublish = false" />

		<CzConfirm
			v-if="confirmReopen"
			:title="t('organizer.results.report.confirmReopen.title')"
			:message="t('organizer.results.report.confirmReopen.message')"
			:confirm-label="t('organizer.results.report.confirmReopen.confirm')"
			@confirm="confirmReopen = false; reopenSession()"
			@cancel="confirmReopen = false" />

		<CzConfirm
			v-if="confirmPublish"
			:title="t('organizer.results.report.confirmPublish.title')"
			:message="t('organizer.results.report.confirmPublish.message')"
			:confirm-label="t('organizer.results.report.confirmPublish.confirm')"
			@confirm="togglePublish"
			@cancel="confirmPublish = false" />
	</div>
</template>
