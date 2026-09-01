<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import { mdiBrain, mdiClipboardTextOutline, mdiCogOutline, mdiCreation, mdiRefresh } from '@mdi/js'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import type { AssemblyDetail, RoundFindings } from '../types'
import FindingCard from './FindingCard.vue'
import CzButton from './ui/CzButton.vue'
import CzEmptyState from './ui/CzEmptyState.vue'
import CzSkeleton from './ui/CzSkeleton.vue'
import CzStatusPill from './ui/CzStatusPill.vue'
import { toast } from './ui/toast'

const props = defineProps<{ assembly: AssemblyDetail }>()

const roundId = ref(props.assembly.rounds[0]?.id ?? '')
const data = ref<RoundFindings | null>(null)
const error = ref('')
const busy = ref(false)

let pollTimer = 0

async function reload(): Promise<void> {
	if (!roundId.value) return
	try {
		data.value = await api.roundFindings(roundId.value)
		error.value = ''
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err)
	}
}

onMounted(() => {
	void reload()
	// analysis jobs complete in the background; refresh periodically
	pollTimer = window.setInterval(() => void reload(), 8000)
})

onBeforeUnmount(() => window.clearInterval(pollTimer))

watch(roundId, () => {
	data.value = null
	void reload()
})

async function analyze(force: boolean): Promise<void> {
	busy.value = true
	try {
		const result = await api.requestAnalysis(roundId.value, force)
		toast(`Analysis queued for ${result.queued} table(s)`)
		await reload()
	} catch (err) {
		toast(err instanceof Error ? err.message : String(err), 'error')
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
		<div v-if="error" class="cz-error">{{ error }}</div>

		<div class="cz-row" style="margin-bottom: 16px">
			<select v-model="roundId" style="min-width: 220px">
				<option v-for="round in assembly.rounds" :key="round.id" :value="round.id">
					Round {{ round.position }} — {{ round.title || 'Untitled' }}
				</option>
			</select>
			<template v-if="data">
				<CzStatusPill :status="data.round_status" />
				<span style="flex: 1"></span>
				<CzButton
					v-if="data.analysis_configured"
					small :icon="mdiRefresh" :disabled="busy"
					@click="analyze(hasAnyFindings())">
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

		<template v-else-if="data">
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

			<template v-else>
				<div v-if="data.cross_table.length || data.round_summary" style="margin-bottom: 24px">
					<h3 style="margin-bottom: 10px">
						Across all tables
						<span v-if="data.tables_with_findings" class="cz-muted" style="font-weight: 400; font-size: 13px">
							— aggregated from {{ data.tables_with_findings }} table(s)
						</span>
					</h3>
					<p v-if="data.round_summary" class="cz-card" style="font-size: 14.5px; font-style: italic">
						<span class="cz-muted" style="font-style: normal; font-size: 12px; display: block; margin-bottom: 4px">AI SUMMARY</span>
						{{ data.round_summary }}
					</p>
					<FindingCard
						v-for="finding in data.cross_table"
						:key="finding.id"
						:finding="finding"
						@changed="reload" />
				</div>

				<template v-for="table in data.tables" :key="table.table_number">
					<div v-if="table.analyzed || table.findings.length" style="margin-bottom: 24px">
						<h3 style="margin-bottom: 10px">Table {{ table.table_number }}</h3>
						<p v-if="table.summary" class="cz-card" style="font-size: 14.5px; font-style: italic">
							<span class="cz-muted" style="font-style: normal; font-size: 12px; display: block; margin-bottom: 4px">AI SUMMARY</span>
							{{ table.summary }}
						</p>
						<p v-if="table.analyzed && !table.findings.length" class="cz-muted" style="font-size: 13.5px">
							Analyzed — no substantive findings for the round question in this discussion.
						</p>
						<FindingCard
							v-for="finding in table.findings"
							:key="finding.id"
							:finding="finding"
							@changed="reload" />
					</div>
				</template>

				<p class="cz-muted" style="font-size: 13px">
					AI findings are drafts until a human approves them; summaries are AI-generated neutral
					descriptions. Every finding cites transcript evidence; “mentioned at N tables” is never
					a measure of participant support.
				</p>
			</template>
		</template>
	</div>
</template>
