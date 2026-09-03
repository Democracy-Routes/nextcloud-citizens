<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import { mdiCheck, mdiChevronDown, mdiChevronUp, mdiClose, mdiPencilOutline } from '@mdi/js'
import { onBeforeUnmount, ref } from 'vue'
import { api } from '../api'
import { timestamp } from '../format'
import { TYPE_LABELS } from '../labels'
import type { FindingData } from '../types'
import CzButton from './ui/CzButton.vue'
import CzStatusPill from './ui/CzStatusPill.vue'
import { toast } from './ui/toast'

const props = defineProps<{ finding: FindingData }>()
const emit = defineEmits<{ changed: []; editing: [open: boolean] }>()

const showEvidence = ref(false)
const editing = ref(false)
const editTitle = ref('')
const editSummary = ref('')
const busy = ref(false)

const TYPE_TONES: Record<string, string> = {
	proposal: 'blue', agreement: 'green', disagreement: 'orange', concern: 'amber',
	question: 'gray', minority_position: 'amber', new_idea: 'blue',
}

const STATUS_MAP: Record<string, string> = {
	DRAFT: 'PROCESSING', APPROVED: 'COMPLETE', EDITED_AND_APPROVED: 'COMPLETE', REJECTED: 'UPLOAD_INCOMPLETE',
}

/** The parent pauses its poll while this is open. A re-analysis deletes the
 * draft findings it replaces, so a refresh mid-edit unmounts this card and the
 * typed text goes with it. */
function setEditing(open: boolean): void {
	editing.value = open
	emit('editing', open)
}

function startEdit(): void {
	editTitle.value = props.finding.title
	editSummary.value = props.finding.summary
	setEditing(true)
}

// a card can vanish for reasons of its own — a round change, the tab closing.
// Without this the parent would hold its id and never poll again.
onBeforeUnmount(() => {
	if (editing.value) emit('editing', false)
})

async function apply(payload: { status?: string; title?: string; summary?: string }, note: string): Promise<void> {
	busy.value = true
	try {
		await api.updateFinding(props.finding.id, payload)
		toast(note)
		setEditing(false)
		emit('changed')
	} catch (err) {
		toast(err instanceof Error ? err.message : String(err), 'error')
	} finally {
		busy.value = false
	}
}

</script>

<template>
	<div class="cz-card" style="padding: 14px 18px">
		<template v-if="editing">
			<div class="cz-field"><label>Title</label><input v-model="editTitle" type="text" /></div>
			<div class="cz-field"><label>Summary</label><textarea v-model="editSummary" rows="3"></textarea></div>
			<div class="cz-row" style="justify-content: flex-end">
				<CzButton variant="tertiary" small @click="setEditing(false)">Cancel</CzButton>
				<CzButton
					variant="primary"
					small
					:disabled="busy"
					@click="apply({ title: editTitle, summary: editSummary, status: 'APPROVED' }, 'Finding edited and approved')">
					Save &amp; approve
				</CzButton>
			</div>
		</template>
		<template v-else>
			<div class="cz-row cz-row--spread" style="align-items: flex-start; flex-wrap: nowrap; gap: 14px">
				<div style="min-width: 0">
					<div class="cz-row" style="gap: 6px; margin-bottom: 4px">
						<span class="cz-pill" :class="`cz-pill--${TYPE_TONES[finding.type] ?? 'gray'}`" style="text-transform: none">
							{{ TYPE_LABELS[finding.type] ?? finding.type.replaceAll('_', ' ') }}
						</span>
						<span v-if="finding.scope === 'round' && finding.mentioned_table_count" class="cz-pill cz-pill--gray" style="text-transform: none">
							Mentioned at {{ finding.mentioned_table_count }} table(s)
						</span>
						<span v-if="finding.support" class="cz-muted" style="font-size: 0.78rem">support: {{ finding.support }}</span>
					</div>
					<strong>{{ finding.title }}</strong>
					<p style="margin: 4px 0 0; font-size: 0.905rem">{{ finding.summary }}</p>
				</div>
				<CzStatusPill :status="STATUS_MAP[finding.status] ?? 'PROCESSING'" :label="finding.status.replaceAll('_', ' ').toLowerCase()" />
			</div>

			<div class="cz-row" style="margin-top: 10px; gap: 6px">
				<CzButton
					v-if="finding.status === 'DRAFT' || finding.status === 'REJECTED'"
					variant="primary" small :icon="mdiCheck" :disabled="busy"
					@click="apply({ status: 'APPROVED' }, 'Finding approved')">
					Approve
				</CzButton>
				<!-- rejecting keeps a finding out of the published report, which is
				     less recoverable than approving it — it should not be the
				     quietest button on the card -->
				<CzButton
					v-if="finding.status !== 'REJECTED'"
					variant="secondary" small :icon="mdiClose" :disabled="busy"
					@click="apply({ status: 'REJECTED' }, 'Finding rejected')">
					Reject
				</CzButton>
				<CzButton variant="tertiary" small :icon="mdiPencilOutline" :disabled="busy" @click="startEdit">
					Edit
				</CzButton>
				<span style="flex: 1"></span>
				<CzButton
					v-if="finding.evidence.length"
					variant="tertiary" small
					:icon="showEvidence ? mdiChevronUp : mdiChevronDown"
					@click="showEvidence = !showEvidence">
					{{ finding.evidence.length }} evidence excerpt(s)
				</CzButton>
			</div>

			<div v-if="showEvidence" class="cz-convo" style="margin-top: 10px; max-height: 260px">
				<div v-for="evidence in finding.evidence" :key="evidence.segment_id" class="cz-convo__seg cz-convo__seg--s1">
					<span class="cz-convo__time">{{ timestamp(evidence.start) }}</span>
					<div class="cz-convo__body">
						<span class="cz-convo__speaker">{{ evidence.speaker || 'SPEAKER' }}</span>
						<p class="cz-convo__text">“{{ evidence.text }}”</p>
					</div>
				</div>
			</div>
		</template>
	</div>
</template>
