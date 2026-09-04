<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import { TYPE_LABELS, TYPE_ORDER, roundHeading } from '../labels'
import { mdiBrain, mdiCheckAll, mdiClipboardTextOutline, mdiCogOutline, mdiCreation, mdiFilterOutline, mdiRefresh } from '@mdi/js'
import { computed, ref, watch } from 'vue'
import { api } from '../api'
import { BACKGROUND_MS } from '../composables/intervals'
import { usePolling } from '../composables/usePolling'
import { describeError } from '../errors'
import type { AssemblyDetail, FindingData, RoundFindings } from '../types'
import FindingCard from './FindingCard.vue'
import CzButton from './ui/CzButton.vue'
import CzConfirm from './ui/CzConfirm.vue'
import CzEmptyState from './ui/CzEmptyState.vue'
import CzFreshness from './ui/CzFreshness.vue'
import CzSkeleton from './ui/CzSkeleton.vue'
import CzStatusPill from './ui/CzStatusPill.vue'
import { toast } from './ui/toast'

const props = defineProps<{ assembly: AssemblyDetail }>()

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

const STATUS_FILTERS: Array<{ value: typeof statusFilter.value; label: string }> = [
	{ value: 'all', label: 'All findings' },
	{ value: 'draft', label: 'Needs review' },
	{ value: 'approved', label: 'Approved' },
	{ value: 'rejected', label: 'Rejected' },
]

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
		toast(`${result.approved} finding(s) approved`)
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
			toast('Nothing to analyze — no table has a transcript ready yet', 'error')
		} else {
			toast(`Analysis queued for ${result.queued} table(s)`)
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
</script>

<template>
	<div>
		<div class="cz-row cz-row--spread" style="margin-bottom: 10px">
			<!-- pausing while an editor is open makes the view stale on
			     purpose, so it has to say when it was last current -->
			<span v-if="polling.paused.value" class="cz-muted" style="font-size: 0.8125rem">
				Paused while you edit
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
			<select v-if="data && hasAnyFindings()" v-model="statusFilter" aria-label="Filter by review status">
				<option v-for="option in STATUS_FILTERS" :key="option.value" :value="option.value">
					{{ option.label }}
				</option>
			</select>
			<select v-if="data && hasAnyFindings()" v-model="typeFilter" aria-label="Filter by finding type">
				<option value="all">All types</option>
				<option v-for="type in TYPE_ORDER" :key="type" :value="type">
					{{ TYPE_LABELS[type] ?? type }}
				</option>
			</select>
			<template v-if="data">
				<CzStatusPill :status="data.round_status" />
				<span style="flex: 1"></span>
				<CzButton
					v-if="draftCount > 0"
					small variant="primary" :icon="mdiCheckAll" :disabled="busy"
					@click="confirmApproveAll = true">
					Approve {{ draftCount }} draft(s)
				</CzButton>
				<CzButton
					v-if="data.analysis_configured"
					small :icon="mdiRefresh" :disabled="busy"
					@click="requestAnalyze">
					{{ hasAnyFindings() ? 'Re-run analysis' : 'Run analysis' }}
				</CzButton>
			</template>
		</div>

		<!-- an assembly with no rounds has nothing to poll for, so the skeleton
		     shimmered forever and the tab looked permanently broken -->
		<CzEmptyState
			v-if="!roundId"
			:icon="mdiClipboardTextOutline"
			title="This assembly has no rounds yet"
			hint="Add a round on the Rounds tab; findings appear here once its tables have been analyzed." />

		<CzSkeleton v-else-if="!data && !error" :rows="4" />

		<template v-else-if="data && shown">
			<CzEmptyState
				v-if="!data.analysis_configured"
				:icon="mdiCogOutline"
				title="AI analysis is not configured"
				hint="An administrator needs to add an analysis API key (Mistral, Ollama Cloud, or any OpenAI-compatible endpoint) in Settings. Analysis then runs automatically after each table is transcribed." />

			<CzEmptyState
				v-else-if="!hasAnyFindings()"
				:icon="mdiBrain"
				:title="anyAnalyzing() ? 'Analysis in progress…' : 'No findings yet'"
				:hint="anyAnalyzing()
					? 'Tables are being analyzed — findings appear here automatically.'
					: 'Findings appear automatically after tables are recorded and transcribed, or run the analysis manually.'">
				<CzButton variant="primary" :icon="mdiCreation" :disabled="busy" @click="analyze(false)">
					Run analysis now
				</CzButton>
			</CzEmptyState>

			<CzEmptyState
				v-else-if="filtering && shownCount === 0"
				:icon="mdiFilterOutline"
				title="No findings match this filter"
				hint="Change the filters above to see the rest of this round's findings." />
			<template v-else>
				<div v-if="shown.cross_table.length || (data.round_summary && !filtering)" style="margin-bottom: 24px">
					<h3 style="margin-bottom: 10px">
						Across all tables
						<span v-if="data.tables_with_findings" class="cz-muted" style="font-weight: 400; font-size: 0.8125rem">
							— aggregated from {{ data.tables_with_findings }} table(s)
						</span>
					</h3>
					<p v-if="data.round_summary" class="cz-card" style="font-size: 0.905rem; font-style: italic">
						<span class="cz-muted" style="font-style: normal; font-size: 0.75rem; display: block; margin-bottom: 4px">AI SUMMARY</span>
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
						<h3 style="margin-bottom: 10px">Table {{ table.table_number }}</h3>
						<p v-if="table.summary" class="cz-card" style="font-size: 0.905rem; font-style: italic">
							<span class="cz-muted" style="font-style: normal; font-size: 0.75rem; display: block; margin-bottom: 4px">AI SUMMARY</span>
							{{ table.summary }}
						</p>
						<p v-if="table.analyzed && !table.findings.length" class="cz-muted" style="font-size: 0.845rem">
							Analyzed — no substantive findings for the round question in this discussion.
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
					AI findings are drafts until a human approves them; summaries are AI-generated neutral
					descriptions. Every finding cites transcript evidence; “mentioned at N tables” is never
					a measure of participant support.
				</p>
			</template>
		</template>
		<CzConfirm
			v-if="confirmApproveAll"
			title="Approve every draft finding?"
			:message="`${draftCount} draft finding(s) in this round will be marked approved and included in the report. Rejected findings are left alone, and you can still edit or reject any of them afterwards.`"
			confirm-label="Approve all drafts"
			@confirm="approveAll"
			@cancel="confirmApproveAll = false" />
		<CzConfirm
			v-if="confirmRerun"
			title="Run the analysis again?"
			:message="
				reviewedCount > 0
					? `Every finding for this round is replaced with freshly generated ones — including the ${reviewedCount} you have already approved or edited. Their wording and your review are lost.`
					: 'Every draft finding for this round is replaced with freshly generated ones.'
			"
			confirm-label="Run analysis again"
			:tone="reviewedCount > 0 ? 'destructive' : 'danger'"
			:confirm-word="reviewedCount > 0 ? 'replace' : undefined"
			@confirm="analyze(true)"
			@cancel="confirmRerun = false" />
	</div>
</template>
