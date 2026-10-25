<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import { TYPE_ORDER, roundHeading, typeLabel } from '../labels'
import { mdiBrain, mdiCancel, mdiCheckAll, mdiClipboardTextOutline, mdiCogOutline, mdiCreation, mdiFilterOutline, mdiRefresh } from '@mdi/js'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../api'
import { BACKGROUND_MS } from '../composables/intervals'
import { usePolling } from '../composables/usePolling'
import { describeError } from '../errors'
import type { AssemblyDetail, FindingData, RoundFindings } from '../types'
import FindingCard from './FindingCard.vue'
import SpeakingBalanceCard from './SpeakingBalanceCard.vue'
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

const roundId = ref(props.assembly.rounds[0]?.id ?? '')
const data = ref<RoundFindings | null>(null)
const error = ref('')
const busy = ref(false)

async function reload(): Promise<void> {
	if (!roundId.value) return
	try {
		data.value = await api.roundFindings(roundId.value)
		error.value = ''
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err)
	}
}

// analysis jobs complete in the background; BACKGROUND_MS is the shared
// constant for exactly that. This tab was the one the polling sweep missed and
// still had a hand-picked 8000 with no visibility gating and no freshness.
const polling = usePolling(reload, { intervalMs: BACKGROUND_MS })

/** Findings with an editor open on them.
 *
 * A background analysis job DELETES the draft findings it replaces, so every
 * id changes; the poll then swaps the list and Vue unmounts the card the
 * organizer was typing in, taking the text with it. Silent, and it lands on
 * the person doing the most careful work in the room.
 *
 * Keyed by id rather than counted, because a count desyncs the moment a card
 * disappears without saying so. */
const editingIds = ref(new Set<string>())

function setEditing(findingId: string, editing: boolean): void {
	const next = new Set(editingIds.value)
	if (editing) next.add(findingId)
	else next.delete(findingId)
	editingIds.value = next
	if (next.size) polling.pause()
	else polling.resume()
}

watch(roundId, () => {
	data.value = null
	// the cards these referred to are gone; holding their ids would pause the
	// poll forever
	editingIds.value = new Set()
	polling.resume()
	void reload()
})

const confirmRerun = ref(false)
const confirmApproveAll = ref(false)

/** Narrowing the list, not changing it.
 *
 * Native selects rather than a chip row: the app has no segmented control, and
 * these inherit the styling, the keyboard behaviour and the 44px touch target
 * the rest of the tab already has. */
const statusFilter = ref<'all' | 'draft' | 'approved' | 'rejected'>('all')
const typeFilter = ref('all')

const STATUS_FILTERS = computed<Array<{ value: typeof statusFilter.value; label: string }>>(() => [
	{ value: 'all', label: t('organizer.results.analysis.filters.all') },
	{ value: 'draft', label: t('organizer.results.analysis.filters.draft') },
	{ value: 'approved', label: t('organizer.results.analysis.filters.approved') },
	{ value: 'rejected', label: t('organizer.results.analysis.filters.rejected') },
])

function keep(finding: FindingData): boolean {
	if (typeFilter.value !== 'all' && finding.type !== typeFilter.value) return false
	if (statusFilter.value === 'draft') return finding.status === 'DRAFT'
	if (statusFilter.value === 'approved')
		return finding.status === 'APPROVED' || finding.status === 'EDITED_AND_APPROVED'
	if (statusFilter.value === 'rejected') return finding.status === 'REJECTED'
	return true
}

/** The filtered view. Every empty state and section guard reads THIS, not the
 * raw payload — otherwise a filter that matches nothing renders section
 * headings with nothing under them and no explanation. */
const shown = computed(() => {
	if (!data.value) return null
	return {
		...data.value,
		cross_table: data.value.cross_table.filter(keep),
		tables: data.value.tables.map((table) => ({
			...table,
			findings: table.findings.filter(keep),
		})),
	}
})

const filtering = computed(() => statusFilter.value !== 'all' || typeFilter.value !== 'all')

const shownCount = computed(() =>
	shown.value
		? shown.value.cross_table.length +
			shown.value.tables.reduce((n, t) => n + t.findings.length, 0)
		: 0,
)

const draftCount = computed(
	() =>
		[
			...(data.value?.cross_table ?? []),
			...(data.value?.tables ?? []).flatMap((t) => t.findings),
		].filter((f) => f.status === 'DRAFT').length,
)

async function approveAll(): Promise<void> {
	confirmApproveAll.value = false
	busy.value = true
	try {
		const result = await api.approveDrafts(roundId.value)
		toast(t('organizer.results.analysis.toast.approved', { count: result.approved }, result.approved))
		await polling.refresh()
	} catch (err) {
		toast(describeError(err).message, 'error')
	} finally {
		busy.value = false
	}
}

/** Findings a person has already dealt with, which a re-run would replace. */
const reviewedCount = computed(() => {
	const perTable = (data.value?.tables ?? []).flatMap((table) => table.findings)
	const crossTable = data.value?.cross_table ?? []
	return [...perTable, ...crossTable].filter((finding) => finding.status !== 'DRAFT').length
})

function requestAnalyze(): void {
	// Re-running passes force=true, which regenerates findings the facilitator
	// has approved or hand-edited. It used to do that behind a plain button
	// with no dialog at all.
	if (hasAnyFindings()) confirmRerun.value = true
	else void analyze(false)
}

async function analyze(force: boolean): Promise<void> {
	confirmRerun.value = false
	busy.value = true
	try {
		const result = await api.requestAnalysis(roundId.value, force)
		if (result.queued === 0) {
			toast(t('organizer.results.analysis.toast.nothingToAnalyze'), 'error')
		} else {
			toast(t('organizer.results.analysis.toast.queued', { count: result.queued }, result.queued))
		}
		await reload()
	} catch (err) {
		toast(describeError(err).message, 'error')
	} finally {
		busy.value = false
	}
}

const hasAnyFindings = () =>
	!!data.value &&
	(data.value.cross_table.length > 0 ||
		!!data.value.round_summary ||
		data.value.tables.some((t) => t.findings.length > 0 || t.analyzed))

const anyAnalyzing = () =>
	!!data.value && data.value.tables.some((t) => t.recording && ['ANALYZING', 'TRANSCRIBING'].includes(t.recording.state))
/** What the jobs are doing, from the jobs themselves.
 *
 * "Analysis is already running for every table" was the whole story while a
 * 429 backed off for eight minutes: nothing said which tables, how long, or
 * why. The payload now carries the newest job per table. */
const LIVE_JOB = new Set(['QUEUED', 'RUNNING', 'RETRY'])

const pendingTables = computed(() =>
	(data.value?.tables ?? []).filter((t) => t.recording?.job && LIVE_JOB.has(t.recording.job.state)),
)

const retryingTables = computed(() =>
	pendingTables.value.filter((t) => t.recording?.job?.state === 'RETRY'),
)

const failedTables = computed(() =>
	(data.value?.tables ?? []).filter((t) => t.recording?.state === 'ANALYSIS_FAILED'),
)

const roundJobFailed = computed(() => data.value?.round_job?.state === 'FAILED')

const queueSummary = computed(() => {
	const counts: Record<string, number> = { RUNNING: 0, QUEUED: 0, RETRY: 0 }
	for (const table of pendingTables.value) counts[table.recording!.job!.state] += 1
	const parts: string[] = []
	if (counts.RUNNING) parts.push(t('organizer.results.analysis.running', { count: counts.RUNNING }, counts.RUNNING))
	if (counts.QUEUED) parts.push(t('organizer.results.analysis.queued', { count: counts.QUEUED }, counts.QUEUED))
	if (counts.RETRY) parts.push(t('organizer.results.analysis.waitingRetry', { count: counts.RETRY }, counts.RETRY))
	return parts.join(', ')
})

async function cancelPending(): Promise<void> {
	busy.value = true
	try {
		const result = await api.cancelAnalysis(roundId.value)
		toast(
			result.running
				? t('organizer.results.analysis.toast.cancelledRunning', { cancelled: result.cancelled, running: result.running })
				: t('organizer.results.analysis.toast.cancelled', { count: result.cancelled }, result.cancelled),
		)
		await polling.refresh()
	} catch (err) {
		toast(describeError(err).message, 'error')
	} finally {
		busy.value = false
	}
}

/** Cross-table findings a person has reviewed; re-clustering replaces them. */
const reviewedCrossTableCount = computed(
	() => (data.value?.cross_table ?? []).filter((finding) => finding.status !== 'DRAFT').length,
)
const confirmRecluster = ref(false)

function requestRecluster(): void {
	if (reviewedCrossTableCount.value > 0) confirmRecluster.value = true
	else void recluster()
}

async function recluster(): Promise<void> {
	confirmRecluster.value = false
	busy.value = true
	try {
		const result = await api.recluster(roundId.value)
		toast(result.queued
			? t('organizer.results.analysis.toast.reclusterQueued')
			: t('organizer.results.analysis.toast.reclusterAlready'))
		await polling.refresh()
	} catch (err) {
		toast(describeError(err).message, 'error')
	} finally {
		busy.value = false
	}
}
</script>

<template>
	<div>
		<div class="cz-row cz-row--spread" style="margin-bottom: 10px">
			<!-- pausing while an editor is open makes the view stale on
			     purpose, so it has to say when it was last current -->
			<span v-if="polling.paused.value" class="cz-muted" style="font-size: 0.8125rem">
				{{ t('organizer.results.analysis.pausedWhileEditing') }}
			</span>
			<span v-else></span>
			<CzFreshness
				:last-success-at="polling.lastSuccessAt.value"
				:consecutive-failures="polling.consecutiveFailures.value"
				@refresh="polling.refresh" />
		</div>

		<div v-if="error" class="cz-error">{{ error }}</div>

		<div class="cz-row" style="margin-bottom: 16px">
			<select v-model="roundId" style="min-width: 220px">
				<option v-for="round in assembly.rounds" :key="round.id" :value="round.id">
					{{ roundHeading(round.position, round.title) }}
				</option>
			</select>
			<select v-if="data && hasAnyFindings()" v-model="statusFilter" :aria-label="t('organizer.results.analysis.filterStatus')">
				<option v-for="option in STATUS_FILTERS" :key="option.value" :value="option.value">
					{{ option.label }}
				</option>
			</select>
			<select v-if="data && hasAnyFindings()" v-model="typeFilter" :aria-label="t('organizer.results.analysis.filterType')">
				<option value="all">{{ t('organizer.results.analysis.allTypes') }}</option>
				<option v-for="type in TYPE_ORDER" :key="type" :value="type">
					{{ typeLabel(type) }}
				</option>
			</select>
			<template v-if="data">
				<CzStatusPill :status="data.round_status" />
				<span style="flex: 1"></span>
				<CzButton
					v-if="draftCount > 0"
					small variant="primary" :icon="mdiCheckAll" :disabled="busy"
					@click="confirmApproveAll = true">
					{{ t('organizer.results.analysis.approveDrafts', { count: draftCount }, draftCount) }}
				</CzButton>
				<CzButton
					v-if="data.analysis_configured"
					small :icon="mdiRefresh" :disabled="busy"
					@click="requestAnalyze">
					{{ hasAnyFindings() ? t('organizer.results.analysis.rerun') : t('organizer.results.analysis.run') }}
				</CzButton>
			</template>
		</div>

		<!-- an assembly with no rounds has nothing to poll for, so the skeleton
		     shimmered forever and the tab looked permanently broken -->
		<CzEmptyState
			v-if="!roundId"
			:icon="mdiClipboardTextOutline"
			:title="t('organizer.results.analysis.noSessionsTitle')"
			:hint="t('organizer.results.analysis.noSessionsHint')" />

		<CzSkeleton v-else-if="!data && !error" :rows="4" />

		<template v-else-if="data && shown">
			<!-- the jobs' own account, before any empty state: a failed or
			     waiting analysis used to hide behind "No findings yet" -->
			<div v-if="pendingTables.length" class="cz-card cz-analysis-jobs">
				<div class="cz-row cz-row--spread">
					<span><strong>{{ t('organizer.results.analysis.inProgress') }}</strong> — {{ queueSummary }}</span>
					<CzButton small :icon="mdiCancel" :disabled="busy" @click="cancelPending">
						{{ t('organizer.results.analysis.cancelPending') }}
					</CzButton>
				</div>
				<div v-for="table in retryingTables" :key="table.table_number" style="margin-top: 6px">
					<span class="cz-muted" style="font-size: 0.8125rem">{{ t('organizer.results.analysis.table', { number: table.table_number }) }}</span>
					<CzFailureNote :state="table.recording!.state" :job="table.recording!.job" />
				</div>
			</div>
			<div v-if="failedTables.length" class="cz-card cz-analysis-jobs">
				<strong>{{ t('organizer.results.analysis.failed') }}</strong> {{ t('organizer.results.analysis.failedFor', { count: failedTables.length }, failedTables.length) }}
				<div v-for="table in failedTables" :key="table.table_number" style="margin-top: 6px">
					<span class="cz-muted" style="font-size: 0.8125rem">{{ t('organizer.results.analysis.table', { number: table.table_number }) }}</span>
					<CzFailureNote
						:state="table.recording!.state"
						:error-code="table.recording!.error_code"
						:job="table.recording!.job" />
				</div>
			</div>
			<div v-if="roundJobFailed" class="cz-card cz-analysis-jobs">
				<div class="cz-row cz-row--spread">
					<strong>{{ t('organizer.results.analysis.clusteringFailed') }}</strong>
					<CzButton small :icon="mdiRefresh" :disabled="busy" @click="requestRecluster">
						{{ t('organizer.results.analysis.rerunClustering') }}
					</CzButton>
				</div>
				<CzFailureNote state="ANALYSIS_FAILED" :job="data.round_job" />
			</div>
			<CzEmptyState
				v-if="!data.analysis_configured"
				:icon="mdiCogOutline"
				:title="t('organizer.results.analysis.notConfiguredTitle')"
				:hint="t('organizer.results.analysis.notConfiguredHint')" />

			<CzEmptyState
				v-else-if="!hasAnyFindings()"
				:icon="mdiBrain"
				:title="anyAnalyzing() ? t('organizer.results.analysis.inProgressTitle') : t('organizer.results.analysis.noFindingsTitle')"
				:hint="anyAnalyzing()
					? t('organizer.results.analysis.inProgressHint')
					: t('organizer.results.analysis.noFindingsHint')">
				<CzButton variant="primary" :icon="mdiCreation" :disabled="busy" @click="analyze(false)">
					{{ t('organizer.results.analysis.runNow') }}
				</CzButton>
			</CzEmptyState>

			<CzEmptyState
				v-else-if="filtering && shownCount === 0"
				:icon="mdiFilterOutline"
				:title="t('organizer.results.analysis.noMatchTitle')"
				:hint="t('organizer.results.analysis.noMatchHint')" />
			<template v-else>
				<!-- the tables side by side: a lopsided table stands out by its
				     ratio; each line measures one table, voices detected not named -->
				<div v-if="(data.speaking_comparison?.length ?? 0) >= 2 && !filtering" class="cz-card cz-compare" data-test="comparison">
					<h3 style="margin: 0 0 4px">{{ t('organizer.results.analysis.comparison.title') }}</h3>
					<p class="cz-muted" style="font-size: 0.8125rem; margin: 0 0 10px">
						{{ t('organizer.results.analysis.comparison.intro') }}
					</p>
					<table class="cz-table">
						<thead>
							<tr>
								<th>{{ t('organizer.results.analysis.comparison.colTable') }}</th>
								<th>{{ t('organizer.results.analysis.comparison.colVoices') }}</th>
								<th>{{ t('organizer.results.analysis.comparison.colLargest') }}</th>
								<th>{{ t('organizer.results.analysis.comparison.colSmallest') }}</th>
								<th>{{ t('organizer.results.analysis.comparison.colRatio') }}</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="row in data.speaking_comparison" :key="row.table_number" :class="{ 'cz-compare--lopsided': (row.ratio ?? 0) >= 4 }">
								<td><strong>{{ t('organizer.results.analysis.table', { number: row.table_number }) }}</strong><span v-if="row.recorder_changed" class="cz-muted"> · {{ t('organizer.results.analysis.comparison.recorderChanged') }}</span></td>
								<td>{{ row.voices }}</td>
								<td>{{ row.largest_percent }}%</td>
								<td>{{ row.smallest_percent }}%</td>
								<td>{{ row.ratio ? `${row.ratio}×` : '—' }}</td>
							</tr>
						</tbody>
					</table>
				</div>
				<div v-if="shown.cross_table.length || (data.round_summary && !filtering)" style="margin-bottom: 24px">
					<h3 style="margin-bottom: 10px">
						{{ t('organizer.results.analysis.acrossTables') }}
						<span v-if="data.tables_with_findings" class="cz-muted" style="font-weight: 400; font-size: 0.8125rem">
							{{ t('organizer.results.analysis.aggregatedFrom', { count: data.tables_with_findings }, data.tables_with_findings) }}
						</span>
					</h3>
					<p class="cz-muted" style="font-size: 0.8125rem; margin: 0 0 8px">
						{{ t('organizer.results.analysis.crossTableNote') }}
					</p>
					<p v-if="data.round_summary" class="cz-card" style="font-size: 0.905rem; font-style: italic">
						<span class="cz-muted" style="font-style: normal; font-size: 0.75rem; display: block; margin-bottom: 4px">{{ t('organizer.results.analysis.aiSummary') }}</span>
						{{ data.round_summary }}
					</p>
					<FindingCard
						v-for="finding in shown.cross_table"
						:key="finding.id"
						:finding="finding"
						@changed="reload"
						@editing="(open: boolean) => setEditing(finding.id, open)" />
				</div>

				<template v-for="table in shown.tables" :key="table.table_number">
					<div v-if="(table.analyzed && !filtering) || table.findings.length" style="margin-bottom: 24px">
						<h3 style="margin-bottom: 10px">{{ t('organizer.results.analysis.table', { number: table.table_number }) }}</h3>
						<p v-if="table.summary" class="cz-card" style="font-size: 0.905rem; font-style: italic">
							<span class="cz-muted" style="font-style: normal; font-size: 0.75rem; display: block; margin-bottom: 4px">{{ t('organizer.results.analysis.aiSummary') }}</span>
							{{ table.summary }}
						</p>
						<!-- talk-time per detected voice at THIS table: diarization
						     labels never carry across tables, so the chart never does -->
						<SpeakingBalanceCard
							v-if="table.speaking_balance && table.speaking_balance.voices.length >= 2"
							:balance="table.speaking_balance" />
						<p v-if="table.analyzed && !table.findings.length" class="cz-muted" style="font-size: 0.845rem">
							{{ t('organizer.results.analysis.analyzedNoFindings') }}
						</p>
						<FindingCard
							v-for="finding in table.findings"
							:key="finding.id"
							:finding="finding"
							@changed="reload"
							@editing="(open: boolean) => setEditing(finding.id, open)" />
					</div>
				</template>

				<p class="cz-muted" style="font-size: 0.8125rem">
					{{ t('organizer.results.analysis.footer') }}
				</p>
			</template>
		</template>
		<CzConfirm
			v-if="confirmApproveAll"
			:title="t('organizer.results.analysis.confirmApprove.title')"
			:message="t('organizer.results.analysis.confirmApprove.message', { count: draftCount }, draftCount)"
			:confirm-label="t('organizer.results.analysis.confirmApprove.confirm')"
			@confirm="approveAll"
			@cancel="confirmApproveAll = false" />
		<CzConfirm
			v-if="confirmRerun"
			:title="t('organizer.results.analysis.confirmRerun.title')"
			:message="
				reviewedCount > 0
					? t('organizer.results.analysis.confirmRerun.messageReviewed', { count: reviewedCount }, reviewedCount)
					: t('organizer.results.analysis.confirmRerun.messageDrafts')
			"
			:confirm-label="t('organizer.results.analysis.confirmRerun.confirm')"
			:tone="reviewedCount > 0 ? 'destructive' : 'danger'"
			:confirm-word="reviewedCount > 0 ? t('organizer.results.analysis.replaceWord') : undefined"
			@confirm="analyze(true)"
			@cancel="confirmRerun = false" />
		<CzConfirm
			v-if="confirmRecluster"
			:title="t('organizer.results.analysis.confirmRecluster.title')"
			:message="t('organizer.results.analysis.confirmRecluster.message', { count: reviewedCrossTableCount }, reviewedCrossTableCount)"
			:confirm-label="t('organizer.results.analysis.confirmRecluster.confirm')"
			tone="destructive"
			:confirm-word="t('organizer.results.analysis.replaceWord')"
			@confirm="recluster"
			@cancel="confirmRecluster = false" />
	</div>
</template>

<style scoped>
.cz-analysis-jobs {
	margin-bottom: 16px;
}
</style>
