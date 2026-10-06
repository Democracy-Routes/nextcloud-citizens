<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
/**
 * One assembly, in three spaces (0.7): Plan (what is set up before the
 * event), Run (the Live tab while it happens), Results (what came out).
 * The nine tabs keep their ids — the Overview's "go to QR codes" link and
 * every spec still name a tab — and are grouped under the three spaces,
 * with a timeline of the sessions above. The space opens where the event
 * is: Plan before it starts, Run while a session is live, Results once it
 * is closed.
 */
import {
	mdiAccountGroup,
	mdiBrain,
	mdiChartBoxOutline,
	mdiClipboardTextOutline,
	mdiFileDocumentOutline,
	mdiFolderMusicOutline,
	mdiMonitorEye,
	mdiPlayCircleOutline,
	mdiQrcode,
	mdiTableFurniture,
	mdiTimelineClockOutline,
	mdiViewDashboardOutline,
} from '@mdi/js'
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../api'
import type { AssemblyDetail, InviteGenerated } from '../types'
import AnalysisTab from './AnalysisTab.vue'
import AssemblyTimeline from './AssemblyTimeline.vue'
import FilesTab from './FilesTab.vue'
import OverviewTab from './OverviewTab.vue'
import ParticipantsTab from './ParticipantsTab.vue'
import ReportTab from './ReportTab.vue'
import QrTab from './QrTab.vue'
import RoundsTab from './RoundsTab.vue'
import TablesTab from './TablesTab.vue'
import MonitorTab from './MonitorTab.vue'
import CzConfirm from './ui/CzConfirm.vue'
import CzTabs from './ui/CzTabs.vue'
import { panelId, tabId, type TabItem } from './ui/tabs'
import CzSkeleton from './ui/CzSkeleton.vue'
import CzStatusPill from './ui/CzStatusPill.vue'
import { toast } from './ui/toast'

const props = defineProps<{ assemblyId: string; freshInvites?: InviteGenerated[] }>()
const emit = defineEmits<{ changed: []; deleted: []; invitesConsumed: [] }>()

const { t } = useI18n()

type Tab =
	| 'overview' | 'rounds' | 'participants' | 'tables' | 'qr' | 'monitor'
	| 'analysis' | 'report' | 'files'
type Space = 'plan' | 'run' | 'results'

const SPACE_TABS: Record<Space, Tab[]> = {
	plan: ['overview', 'rounds', 'participants', 'tables', 'qr'],
	run: ['monitor'],
	results: ['analysis', 'report', 'files'],
}

function spaceOf(tab: Tab): Space {
	return (Object.keys(SPACE_TABS) as Space[]).find((space) => SPACE_TABS[space].includes(tab)) ?? 'plan'
}

const assembly = ref<AssemblyDetail | null>(null)
const error = ref('')
// a freshly created assembly lands on its printable QR sheet
const tab = ref<Tab>(props.freshInvites?.length ? 'qr' : 'overview')
const confirmDelete = ref(false)
// where each space was left, so switching back returns there
const lastTab: Partial<Record<Space, Tab>> = {}

const space = computed<Space>({
	get: () => spaceOf(tab.value),
	set: (next) => {
		lastTab[spaceOf(tab.value)] = tab.value
		tab.value = lastTab[next] ?? SPACE_TABS[next][0]
	},
})

/** Where the event is: Plan before it starts, Run while a session is
 * live, Results once it is closed or its analysis is under way. */
function tabForState(detail: AssemblyDetail): Tab {
	if (detail.closed_at || detail.status === 'COMPLETE' || detail.status === 'REVIEW') return 'report'
	if (detail.status === 'PROCESSING') return 'analysis'
	if (detail.status === 'ACTIVE' || detail.rounds.some((round) => round.status === 'ACTIVE')) return 'monitor'
	return 'overview'
}

const TAB_ICONS: Array<{ id: Tab; icon: string }> = [
	{ id: 'overview', icon: mdiViewDashboardOutline },
	{ id: 'rounds', icon: mdiTimelineClockOutline },
	{ id: 'participants', icon: mdiAccountGroup },
	{ id: 'tables', icon: mdiTableFurniture },
	{ id: 'qr', icon: mdiQrcode },
	{ id: 'monitor', icon: mdiMonitorEye },
	{ id: 'analysis', icon: mdiBrain },
	{ id: 'report', icon: mdiFileDocumentOutline },
	{ id: 'files', icon: mdiFolderMusicOutline },
]
const SPACE_ICONS: Record<Space, string> = {
	plan: mdiClipboardTextOutline,
	run: mdiPlayCircleOutline,
	results: mdiChartBoxOutline,
}
// computed, not module constants, so the labels follow a locale change
const spaces = computed<TabItem[]>(() =>
	(Object.keys(SPACE_TABS) as Space[]).map((id) => ({
		id, icon: SPACE_ICONS[id], label: t(`organizer.navigation.spaces.${id}`),
	})),
)
const subtabs = computed<TabItem[]>(() =>
	TAB_ICONS.filter(({ id }) => SPACE_TABS[space.value].includes(id)).map(({ id, icon }) => ({
		id, icon, label: t(`organizer.shell.detail.tabs.${id}`),
	})),
)

let placed = false
async function reload(): Promise<void> {
	try {
		assembly.value = await api.getAssembly(props.assemblyId)
		// the first load opens the space the event is in; later reloads
		// (an edit, a poll) must not move the organizer around
		if (!placed) {
			placed = true
			if (!props.freshInvites?.length) tab.value = tabForState(assembly.value)
		}
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
		toast(t('organizer.shell.detail.deleted'))
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
					<!-- a standalone Session is never presented as an assembly -->
					<p v-if="assembly.kind === 'session'" class="cz-muted cz-eyebrow">{{ t('organizer.shell.detail.sessionEyebrow') }}</p>
					<h2 style="overflow-wrap: anywhere">{{ assembly.name }}</h2>
					<p v-if="assembly.kind === 'session'" class="cz-muted" style="margin: 4px 0 0">
						<template v-if="assembly.recording_mode === 'plenary'">{{ t('organizer.shell.detail.wholeRoom') }}</template>
						<template v-else>{{ t('organizer.shell.detail.tableCount', { count: assembly.default_table_count }, assembly.default_table_count) }}</template> ·
						{{ assembly.language.toUpperCase() }}
					</p>
					<p v-else class="cz-muted" style="margin: 4px 0 0">
						{{ t('organizer.shell.detail.participantCount', { count: assembly.participant_count, expected: assembly.expected_participants }) }} ·
						<template v-if="assembly.recording_mode === 'plenary'">{{ t('organizer.shell.detail.plenaryMode') }}</template>
						<template v-else>{{ t('organizer.shell.detail.tableCount', { count: assembly.default_table_count }, assembly.default_table_count) }}</template> ·
						{{ t('organizer.shell.detail.sessionCount', { count: assembly.rounds.length }, assembly.rounds.length) }} ·
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

			<!-- the event at a glance; a session opens the Run space on it -->
			<AssemblyTimeline :assembly="assembly" @open="tab = 'monitor'" />

			<!-- Plan / Run / Results, then the space's own tabs -->
			<CzTabs v-model="space" :tabs="spaces" id-prefix="assembly-space" class="cz-spaces" data-test="spaces" />
			<CzTabs v-if="subtabs.length > 1" v-model="tab" :tabs="subtabs" id-prefix="assembly" class="cz-subtabs" data-test="subtabs" />

			<div
				:id="panelId('assembly', tab)"
				role="tabpanel"
				:aria-labelledby="tabId(subtabs.length > 1 ? 'assembly' : 'assembly-space', subtabs.length > 1 ? tab : space)"
				tabindex="0">
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
				@consumed="emit('invitesConsumed')"
				@changed="reload" />
			<MonitorTab v-else-if="tab === 'monitor'" :assembly="assembly" @changed="reload" />
			<AnalysisTab v-else-if="tab === 'analysis'" :assembly="assembly" />
			<ReportTab v-else-if="tab === 'report'" :assembly="assembly" @changed="reload" />
			<FilesTab v-else :assembly="assembly" />
			</div>
		</template>

		<CzConfirm
			v-if="confirmDelete && assembly"
			:title="t('organizer.shell.detail.deleteTitle')"
			:message="t('organizer.shell.detail.deleteMessage', { name: assembly.name })"
			:confirm-label="t('organizer.shell.detail.deleteConfirm')"
			tone="destructive"
			:confirm-word="assembly.name"
			@confirm="deleteAssembly"
			@cancel="confirmDelete = false" />
	</div>
</template>

<style>
/* the three spaces read as the page's main navigation; the sub-tabs as a
   lighter row beneath it */
#citizens-app .cz-spaces { margin-bottom: 0; border-bottom-width: 2px; }
#citizens-app .cz-spaces .cz-tab { font-weight: 700; }
#citizens-app .cz-subtabs { margin-top: 6px; border-bottom-width: 1px; }
#citizens-app .cz-subtabs .cz-tab { font-size: 0.875rem; }
</style>
