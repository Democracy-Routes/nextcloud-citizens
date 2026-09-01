<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import { mdiDownloadOutline, mdiFileDocumentOutline } from '@mdi/js'
import { onMounted, ref } from 'vue'
import SvgIcon from '../../components/ui/SvgIcon.vue'
import { groupByType, TYPE_LABELS } from '../../labels'
import { recorderApi, type JoinResult, type PublishedReport } from '../api'
import { downloadBlob } from '../../download'

/*
 * The assembly report as published by the organizer (approved findings and
 * AI summaries only). Participants can read it at the table and download the
 * PDF to keep.
 */

const props = defineProps<{ session: JoinResult }>()
const emit = defineEmits<{ back: [] }>()

const report = ref<PublishedReport | null>(null)
const error = ref('')
const downloading = ref(false)
const downloadNote = ref('')

onMounted(async () => {
	try {
		report.value = await recorderApi.report(props.session.session_token)
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err)
	}
})

async function downloadPdf(): Promise<void> {
	downloading.value = true
	try {
		const blob = await recorderApi.reportPdf(props.session.session_token)
		downloadBlob(
			blob,
			`${props.session.assembly.name.slice(0, 40).replace(/ /g, '-')}-report.pdf`,
		)
		downloadNote.value = 'PDF saved to this phone’s downloads.'
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err)
	} finally {
		downloading.value = false
	}
}
</script>

<template>
	<div class="rc-fill">
		<div class="rc-header">
			<span class="rc-table-badge">TABLE {{ session.table_number }}</span>
		</div>

		<div class="rc-scroll">
			<div v-if="error" class="rc-alert">{{ error }}</div>

			<template v-else-if="report">
				<div class="rc-card">
					<p class="rc-eyebrow" style="margin-bottom: 4px">
						<SvgIcon :path="mdiFileDocumentOutline" :size="13" /> Assembly report
					</p>
					<h1 style="font-size: 20px">{{ report.assembly.name }}</h1>
					<p class="rc-muted" style="margin: 6px 0 0; font-size: 13px">
						{{ report.assembly.participants }} participants ·
						{{ report.assembly.tables }} tables
					</p>
				</div>

				<div v-for="round in report.rounds" :key="round.position" class="rc-card">
					<p class="rc-eyebrow" style="margin-bottom: 4px">
						Round {{ round.position }} — {{ round.title || 'Untitled' }}
					</p>
					<p v-if="round.question" class="rc-question" style="margin: 0 0 10px">
						{{ round.question }}
					</p>
					<template v-if="round.summary">
						<p class="rc-eyebrow" style="margin-bottom: 2px">AI summary</p>
						<p style="font-size: 14.5px; margin: 0 0 10px">{{ round.summary }}</p>
					</template>

					<template v-for="group in groupByType(round.cross_table)" :key="group.type">
						<p
							class="rc-eyebrow"
							style="margin: 8px 0 4px"
							:style="{ color: group.type === 'disagreement' ? 'var(--rc-amber)' : 'var(--rc-blue)' }">
							{{ group.label }}
						</p>
						<div v-for="finding in group.findings" :key="finding.id" style="margin: 0 0 12px">
							<p style="font-weight: 700; font-size: 14.5px; margin: 0">{{ finding.title }}</p>
							<p v-if="finding.mentioned_table_count" class="rc-muted" style="font-size: 12.5px; margin: 1px 0">
								Mentioned at {{ finding.mentioned_table_count }} table(s)
							</p>
							<p style="font-size: 14px; margin: 3px 0 0">{{ finding.summary }}</p>
						</div>
					</template>

					<template v-for="table in round.tables" :key="table.table_number">
						<template v-if="table.summary || table.findings.length">
							<p class="rc-eyebrow" style="margin: 10px 0 2px">Table {{ table.table_number }}</p>
							<p v-if="table.summary" style="font-size: 14px; margin: 0 0 8px">{{ table.summary }}</p>
							<div v-for="finding in table.findings" :key="finding.id" style="margin: 0 0 10px">
								<p style="font-weight: 700; font-size: 14px; margin: 0">
									{{ TYPE_LABELS[finding.type] ?? finding.type }}: {{ finding.title }}
								</p>
								<p style="font-size: 13.5px; margin: 3px 0 0">{{ finding.summary }}</p>
							</div>
						</template>
					</template>
				</div>

				<p class="rc-muted" style="font-size: 12px; line-height: 1.5">
					{{ report.methodology_note }}
				</p>
				<p v-if="downloadNote" class="rc-note">{{ downloadNote }}</p>
			</template>

			<div v-else class="rc-hero" style="padding-top: 20vh">
				<span class="rc-spin" style="width: 26px; height: 26px"></span>
			</div>
		</div>

		<div class="rc-actions">
			<button v-if="report" class="rc-btn rc-primary" :disabled="downloading" @click="downloadPdf">
				<SvgIcon :path="mdiDownloadOutline" :size="20" />
				{{ downloading ? 'Preparing PDF…' : 'Download PDF' }}
			</button>
			<button class="rc-btn rc-subtle" @click="emit('back')">Back</button>
		</div>
	</div>
</template>
