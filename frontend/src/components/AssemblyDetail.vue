<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import {
	mdiAccountGroup,
	mdiBrain,
	mdiFileDocumentOutline,
	mdiFolderMusicOutline,
	mdiMonitorEye,
	mdiQrcode,
	mdiTableFurniture,
	mdiTimelineClockOutline,
	mdiViewDashboardOutline,
} from '@mdi/js'
import { onMounted, ref } from 'vue'
import { api } from '../api'
import type { AssemblyDetail, InviteGenerated } from '../types'
import AnalysisTab from './AnalysisTab.vue'
import FilesTab from './FilesTab.vue'
import OverviewTab from './OverviewTab.vue'
import ParticipantsTab from './ParticipantsTab.vue'
import ReportTab from './ReportTab.vue'
import QrTab from './QrTab.vue'
import RoundsTab from './RoundsTab.vue'
import TablesTab from './TablesTab.vue'
import MonitorTab from './MonitorTab.vue'
import CzConfirm from './ui/CzConfirm.vue'
import CzSkeleton from './ui/CzSkeleton.vue'
import CzStatusPill from './ui/CzStatusPill.vue'
import SvgIcon from './ui/SvgIcon.vue'
import { toast } from './ui/toast'

const props = defineProps<{ assemblyId: string; freshInvites?: InviteGenerated[] }>()
const emit = defineEmits<{ changed: []; deleted: []; invitesConsumed: [] }>()

type Tab =
	| 'overview' | 'rounds' | 'participants' | 'tables' | 'qr' | 'monitor'
	| 'analysis' | 'report' | 'files'

const assembly = ref<AssemblyDetail | null>(null)
const error = ref('')
// a freshly created assembly lands on its printable QR sheet
const tab = ref<Tab>(props.freshInvites?.length ? 'qr' : 'overview')
const confirmDelete = ref(false)

const TABS: Array<{ id: Tab; label: string; icon: string }> = [
	{ id: 'overview', label: 'Overview', icon: mdiViewDashboardOutline },
	{ id: 'rounds', label: 'Rounds', icon: mdiTimelineClockOutline },
	{ id: 'participants', label: 'Participants', icon: mdiAccountGroup },
	{ id: 'tables', label: 'Tables', icon: mdiTableFurniture },
	{ id: 'qr', label: 'QR codes', icon: mdiQrcode },
	{ id: 'monitor', label: 'Live', icon: mdiMonitorEye },
	{ id: 'analysis', label: 'Analysis', icon: mdiBrain },
	{ id: 'report', label: 'Report', icon: mdiFileDocumentOutline },
	{ id: 'files', label: 'Files', icon: mdiFolderMusicOutline },
]

async function reload(): Promise<void> {
	try {
		assembly.value = await api.getAssembly(props.assemblyId)
		emit('changed')
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err)
	}
}

onMounted(reload)

async function deleteAssembly(): Promise<void> {
	confirmDelete.value = false
	try {
		await api.deleteAssembly(props.assemblyId)
		toast('Assembly deleted')
		emit('deleted')
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err)
	}
}
</script>

<template>
	<div class="cz-page">
		<div v-if="error" class="cz-error">{{ error }}</div>
		<CzSkeleton v-if="!assembly && !error" :rows="4" :height="64" />

		<template v-if="assembly">
			<div class="cz-pagehead">
				<div style="min-width: 0">
					<h2 style="overflow-wrap: anywhere">{{ assembly.name }}</h2>
					<p class="cz-muted" style="margin: 4px 0 0">
						{{ assembly.participant_count }} / {{ assembly.expected_participants }} participants ·
						{{ assembly.default_table_count }} tables · {{ assembly.rounds.length }} rounds ·
						{{ assembly.language.toUpperCase() }}
					</p>
				</div>
				<div class="cz-row" style="flex-wrap: nowrap">
					<CzStatusPill :status="assembly.status" />
					<!-- Deleting the assembly is the most destructive action in the
					     app, and as a small grey icon here it was indistinguishable
					     from the Edit and Move icons elsewhere: one mis-click plus
					     Enter destroyed everything. It now lives in a labelled
					     danger zone on the Overview tab, behind a typed
					     confirmation. -->
				</div>
			</div>

			<div class="cz-tabs" role="tablist">
				<button
					v-for="item in TABS"
					:key="item.id"
					class="cz-tab"
					:class="{ 'cz-tab--active': tab === item.id }"
					role="tab"
					:aria-selected="tab === item.id"
					@click="tab = item.id">
					<SvgIcon :path="item.icon" :size="17" />
					{{ item.label }}
				</button>
			</div>

			<OverviewTab
				v-if="tab === 'overview'"
				:assembly="assembly"
				@navigate="(t: Tab) => (tab = t)"
				@changed="reload"
				@request-delete="confirmDelete = true" />
			<RoundsTab v-else-if="tab === 'rounds'" :assembly="assembly" @changed="reload" />
			<ParticipantsTab v-else-if="tab === 'participants'" :assembly-id="assembly.id" @changed="reload" />
			<TablesTab v-else-if="tab === 'tables'" :assembly="assembly" />
			<QrTab
				v-else-if="tab === 'qr'"
				:assembly="assembly"
				:initial-generated="freshInvites"
				@consumed="emit('invitesConsumed')" />
			<MonitorTab v-else-if="tab === 'monitor'" :assembly="assembly" @changed="reload" />
			<AnalysisTab v-else-if="tab === 'analysis'" :assembly="assembly" />
			<ReportTab v-else-if="tab === 'report'" :assembly="assembly" @changed="reload" />
			<FilesTab v-else :assembly="assembly" />
		</template>

		<CzConfirm
			v-if="confirmDelete && assembly"
			title="Delete assembly?"
			:message="`“${assembly.name}” and all of its rounds, transcripts and reports will be permanently deleted — including every audio file stored on the server.`"
			confirm-label="Delete assembly"
			tone="destructive"
			:confirm-word="assembly.name"
			@confirm="deleteAssembly"
			@cancel="confirmDelete = false" />
	</div>
</template>
