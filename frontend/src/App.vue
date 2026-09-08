<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import { mdiAccountVoice, mdiChevronLeft, mdiChevronRight, mdiCog, mdiMenu, mdiPlus } from '@mdi/js'
import { computed, onMounted, ref } from 'vue'
import { describeError, type UiError } from './errors'
import { api, ApiError } from './api'
import AssemblyDetail from './components/AssemblyDetail.vue'
import AssemblyWizard from './components/AssemblyWizard.vue'
import SettingsView from './components/SettingsView.vue'
import CzButton from './components/ui/CzButton.vue'
import CzError from './components/ui/CzError.vue'
import CzToasts from './components/ui/CzToasts.vue'
import SvgIcon from './components/ui/SvgIcon.vue'
import type { Assembly, InviteGenerated } from './types'

type View = { name: 'empty' } | { name: 'create' } | { name: 'detail'; id: string } | { name: 'settings' }

const assemblies = ref<Assembly[]>([])
const loaded = ref(false)
const view = ref<View>({ name: 'empty' })
const isAdmin = ref(false)
const sidebarOpen = ref(false)
// Desktop collapse of the assemblies column, like Calendar's navigation
// toggle. Remembered per browser; localStorage can throw in private windows,
// so both sides are guarded and the default is simply "open".
const sidebarCollapsed = ref(false)
try {
	sidebarCollapsed.value = localStorage.getItem('citizens-sidebar-collapsed') === '1'
} catch {
	/* default open */
}

function toggleSidebar(): void {
	sidebarCollapsed.value = !sidebarCollapsed.value
	try {
		localStorage.setItem('citizens-sidebar-collapsed', sidebarCollapsed.value ? '1' : '0')
	} catch {
		/* preference simply not remembered */
	}
}
// QR codes generated at creation: handed to the detail view exactly once
/** QR codes from a just-created assembly, handed to the detail view.
 *
 * Keyed by assembly, because it is app-level state consumed by whatever mounts
 * next: if @invites-consumed never fired (QrTab throwing on mount was enough),
 * the NEXT assembly opened was forced onto its QR tab and shown the previous
 * assembly's codes under its own name.
 */
const freshInvites = ref<{ assemblyId: string; invites: InviteGenerated[] } | null>(null)

const STATUS_TONE: Record<string, string> = {
	DRAFT: 'gray', READY: 'blue', ACTIVE: 'red', PROCESSING: 'amber', REVIEW: 'blue', COMPLETE: 'green',
}

const selectedId = computed(() => (view.value.name === 'detail' ? view.value.id : ''))

const loadError = ref<UiError | null>(null)

async function loadAssemblies(selectFirst = false): Promise<void> {
	try {
		assemblies.value = await api.listAssemblies()
		loadError.value = null
		if (selectFirst && view.value.name === 'empty' && assemblies.value.length > 0) {
			view.value = { name: 'detail', id: assemblies.value[0].id }
		}
	} catch (err) {
		// Without this the list stayed empty and the app said "No assemblies
		// yet", inviting the facilitator to create the assembly they already
		// had — during the event, with the API merely unreachable.
		loadError.value = describeError(err)
	} finally {
		loaded.value = true
	}
}

onMounted(async () => {
	void loadAssemblies(true)
	try {
		await api.adminPing()
		isAdmin.value = true
	} catch (err) {
		// Only a definite "you are not an administrator" hides Settings. Any
		// other failure keeps it visible so the admin sees the real error on
		// the page — a broken check once made Settings vanish with no
		// explanation for someone who was entitled to it.
		isAdmin.value = !(err instanceof ApiError && err.status === 403)
	}
})

function open(id: string): void {
	view.value = { name: 'detail', id }
	sidebarOpen.value = false
}

function openCreate(): void {
	freshInvites.value = null
	view.value = { name: 'create' }
	sidebarOpen.value = false
}

function openSettings(): void {
	view.value = { name: 'settings' }
	sidebarOpen.value = false
}

async function onCreated(id: string, invites: InviteGenerated[]): Promise<void> {
	freshInvites.value = { assemblyId: id, invites }
	// Switch FIRST. Reloading the sidebar before switching meant that a failure
	// there left the wizard on screen with its button enabled, and the next
	// click created a second assembly.
	view.value = { name: 'detail', id }
	await loadAssemblies()
}

async function onDeleted(): Promise<void> {
	await loadAssemblies()
	view.value = assemblies.value.length
		? { name: 'detail', id: assemblies.value[0].id }
		: { name: 'empty' }
}
</script>

<template>
	<aside class="cz-sidebar" :class="{ 'cz-sidebar--open': sidebarOpen, 'cz-sidebar--collapsed': sidebarCollapsed }">
		<div class="cz-sidebar__top">
			<CzButton variant="primary" :icon="mdiPlus" wide @click="openCreate">New assembly</CzButton>
		</div>
		<nav class="cz-sidebar__list">
			<button
				v-for="assembly in assemblies"
				:key="assembly.id"
				class="cz-navitem"
				:class="{ 'cz-navitem--active': assembly.id === selectedId }"
				@click="open(assembly.id)">
				<!-- the assembly's state was conveyed by hue and nothing else -->
				<span
					class="cz-dot"
					:class="`cz-dot--${STATUS_TONE[assembly.status] ?? 'gray'}`"
					role="img"
					:aria-label="assembly.status.replaceAll('_', ' ').toLowerCase()"
					:title="assembly.status.replaceAll('_', ' ').toLowerCase()"></span>
				<span class="cz-navitem__body">
					<span class="cz-navitem__name">{{ assembly.name }}</span>
					<span class="cz-navitem__meta">
						{{ assembly.expected_participants }} participants · {{ assembly.default_table_count }} tables
					</span>
				</span>
			</button>
			<div v-if="loadError" style="padding: 10px">
				<CzError :error="loadError" @retry="loadAssemblies()" />
			</div>
			<p
				v-else-if="loaded && assemblies.length === 0"
				class="cz-muted"
				style="padding: 12px; font-size: 0.8125rem">
				No assemblies yet.
			</p>
		</nav>
		<div v-if="isAdmin" class="cz-sidebar__bottom">
			<button
				class="cz-navitem"
				:class="{ 'cz-navitem--active': view.name === 'settings' }"
				@click="openSettings">
				<SvgIcon :path="mdiCog" :size="18" />
				<span class="cz-navitem__body"><span class="cz-navitem__name">Settings</span></span>
			</button>
		</div>
	</aside>

	<div v-if="sidebarOpen" class="cz-scrim" @click="sidebarOpen = false"></div>

	<main class="cz-content">
		<button
			class="cz-sidebar-toggle"
			:class="{ 'cz-sidebar-toggle--collapsed': sidebarCollapsed }"
			:aria-label="sidebarCollapsed ? 'Show assembly list' : 'Hide assembly list'"
			:title="sidebarCollapsed ? 'Show assembly list' : 'Hide assembly list'"
			@click="toggleSidebar">
			<SvgIcon :path="sidebarCollapsed ? mdiChevronRight : mdiChevronLeft" :size="20" />
		</button>
		<div class="cz-mobilebar">
			<CzButton :icon="mdiMenu" small @click="sidebarOpen = true">Assemblies</CzButton>
		</div>

		<div v-if="view.name === 'empty' && loadError" class="cz-page">
			<!-- the list failed to load; there may well BE assemblies, so do not
			     invite the facilitator to create one they already have -->
			<CzError :error="loadError" @retry="loadAssemblies(true)" />
		</div>

		<div v-else-if="view.name === 'empty'" class="cz-page">
			<div class="cz-empty" style="padding-top: 12vh">
				<div class="cz-empty__icon"><SvgIcon :path="mdiAccountVoice" :size="44" /></div>
				<h3 class="cz-empty__title">Welcome to Citizens</h3>
				<p class="cz-empty__hint">
					Run in-person citizens' assemblies: one phone per table records the discussion safely,
					even with unstable connectivity, and transcripts arrive automatically.
				</p>
				<div class="cz-empty__action">
					<CzButton variant="primary" :icon="mdiPlus" @click="openCreate">Create your first assembly</CzButton>
				</div>
			</div>
		</div>

		<AssemblyWizard
			v-else-if="view.name === 'create'"
			@cancel="view = assemblies.length ? { name: 'detail', id: assemblies[0].id } : { name: 'empty' }"
			@created="onCreated" />

		<SettingsView v-else-if="view.name === 'settings'" />

		<AssemblyDetail
			v-else-if="view.name === 'detail'"
			:key="view.id"
			:assembly-id="view.id"
			:fresh-invites="freshInvites?.assemblyId === view.id ? freshInvites.invites : []"
			@changed="loadAssemblies()"
			@invites-consumed="freshInvites = null"
			@deleted="onDeleted" />
	</main>

	<CzToasts />
</template>
