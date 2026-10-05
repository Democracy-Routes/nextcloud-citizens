<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import { mdiChevronLeft, mdiChevronRight, mdiCog, mdiHomeOutline, mdiMenu } from '@mdi/js'
import { computed, onMounted, ref } from 'vue'
import { describeError, type UiError } from './errors'
import { api, ApiError } from './api'
import AssemblyDetail from './components/AssemblyDetail.vue'
import AssemblyWizard from './components/AssemblyWizard.vue'
import HomeView from './components/HomeView.vue'
import SessionWizard from './components/SessionWizard.vue'
import SettingsView from './components/SettingsView.vue'
import CzButton from './components/ui/CzButton.vue'
import CzError from './components/ui/CzError.vue'
import CzToasts from './components/ui/CzToasts.vue'
import SvgIcon from './components/ui/SvgIcon.vue'
import type { Assembly, InviteGenerated } from './types'

type View =
	| { name: 'home' }
	| { name: 'create' }
	| { name: 'create-session' }
	| { name: 'detail'; id: string }
	| { name: 'settings' }

const assemblies = ref<Assembly[]>([])
const loaded = ref(false)
// Home is where everyone lands: Record now, Start a Session, Create an
// Assembly. The app used to open the first assembly, which presumed there
// was one to configure.
const view = ref<View>({ name: 'home' })
const isAdmin = ref(false)
const sidebarOpen = ref(false)
// Desktop collapse of the sidebar column, like Calendar's navigation
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
/** QR codes from a just-created assembly or Session, handed to the detail view.
 *
 * Keyed by container, because it is app-level state consumed by whatever
 * mounts next: if @invites-consumed never fired (QrTab throwing on mount was
 * enough), the NEXT one opened was forced onto its QR tab and shown the
 * previous codes under its own name.
 */
const freshInvites = ref<{ assemblyId: string; invites: InviteGenerated[] } | null>(null)

const STATUS_TONE: Record<string, string> = {
	DRAFT: 'gray', READY: 'blue', ACTIVE: 'red', PROCESSING: 'amber', REVIEW: 'blue', COMPLETE: 'green',
}

const selectedId = computed(() => (view.value.name === 'detail' ? view.value.id : ''))

// A standalone Session is stored behind a container row of kind "session";
// the list shows it as a Session, under its question, never as an assembly.
const sessions = computed(() => assemblies.value.filter((a) => a.kind === 'session'))
const events = computed(() => assemblies.value.filter((a) => a.kind !== 'session'))

const loadError = ref<UiError | null>(null)

async function loadAssemblies(): Promise<void> {
	try {
		assemblies.value = await api.listAssemblies()
		loadError.value = null
	} catch (err) {
		// Without this the list stayed empty and the app said "nothing yet",
		// inviting the facilitator to create the assembly they already
		// had — during the event, with the API merely unreachable.
		loadError.value = describeError(err)
	} finally {
		loaded.value = true
	}
}

onMounted(async () => {
	void loadAssemblies()
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

function goHome(): void {
	view.value = { name: 'home' }
	sidebarOpen.value = false
}

function openCreate(): void {
	freshInvites.value = null
	view.value = { name: 'create' }
	sidebarOpen.value = false
}

function openCreateSession(): void {
	freshInvites.value = null
	view.value = { name: 'create-session' }
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
	view.value = { name: 'home' }
}

/* ---- Record now: a one-table Session and this phone as its recorder ---- */

const recordNowBusy = ref(false)
const recordNowError = ref('')
// shown when the browser refused to open the recorder tab itself
const recorderUrl = ref('')

/** The Nextcloud page language, when it is one the server transcribes. */
function uiLanguage(): string {
	const lang = (document.documentElement.lang || 'en').slice(0, 2).toLowerCase()
	return ['en', 'it', 'de', 'fr', 'es'].includes(lang) ? lang : 'en'
}

async function recordNow(): Promise<void> {
	recordNowBusy.value = true
	recordNowError.value = ''
	recorderUrl.value = ''
	try {
		const made = await api.recordNow({ language: uiLanguage() })
		// The recorder is a separate public page: open it beside the organizer
		// so the Session's Live and Files tabs stay a click away. A browser that
		// blocks the popup gets an explicit link instead of nothing.
		const opened = window.open(made.recorder_url, '_blank', 'noopener')
		if (!opened) recorderUrl.value = made.recorder_url
		await loadAssemblies()
	} catch (err) {
		recordNowError.value = err instanceof Error ? err.message : String(err)
	} finally {
		recordNowBusy.value = false
	}
}
</script>

<template>
	<aside class="cz-sidebar" :class="{ 'cz-sidebar--open': sidebarOpen, 'cz-sidebar--collapsed': sidebarCollapsed }">
		<div class="cz-sidebar__top">
			<CzButton variant="primary" :icon="mdiHomeOutline" wide @click="goHome">Home</CzButton>
		</div>
		<nav class="cz-sidebar__list">
			<p v-if="sessions.length" class="cz-sidebar__group">Sessions</p>
			<button
				v-for="session in sessions"
				:key="session.id"
				class="cz-navitem"
				:class="{ 'cz-navitem--active': session.id === selectedId }"
				@click="open(session.id)">
				<span
					class="cz-dot"
					:class="`cz-dot--${STATUS_TONE[session.status] ?? 'gray'}`"
					role="img"
					:aria-label="session.status.replaceAll('_', ' ').toLowerCase()"
					:title="session.status.replaceAll('_', ' ').toLowerCase()"></span>
				<span class="cz-navitem__body">
					<span class="cz-navitem__name">{{ session.name }}</span>
					<span class="cz-navitem__meta">
						Session · {{ session.default_table_count }} {{ session.default_table_count === 1 ? 'table' : 'tables' }}
					</span>
				</span>
			</button>
			<p v-if="events.length && sessions.length" class="cz-sidebar__group">Assemblies</p>
			<button
				v-for="assembly in events"
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
				No sessions or assemblies yet.
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
			:aria-label="sidebarCollapsed ? 'Show the list' : 'Hide the list'"
			:title="sidebarCollapsed ? 'Show the list' : 'Hide the list'"
			@click="toggleSidebar">
			<SvgIcon :path="sidebarCollapsed ? mdiChevronRight : mdiChevronLeft" :size="20" />
		</button>
		<div class="cz-mobilebar">
			<CzButton :icon="mdiMenu" small @click="sidebarOpen = true">Sessions</CzButton>
		</div>

		<HomeView
			v-if="view.name === 'home'"
			:recording="recordNowBusy"
			:recorder-url="recorderUrl"
			:error="recordNowError"
			@record-now="recordNow"
			@start-session="openCreateSession"
			@create-assembly="openCreate" />

		<SessionWizard
			v-else-if="view.name === 'create-session'"
			@cancel="goHome"
			@created="onCreated" />

		<AssemblyWizard
			v-else-if="view.name === 'create'"
			@cancel="goHome"
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
