<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
/**
 * Settings: four tabs — Transcription, AI, Organisation, About — each a
 * column of cards, one concern per card, each with its own Save.
 *
 * The page used to be three tabs with one Save for all of them, so an admin
 * who came to change a single Vosk URL also committed whatever was sitting
 * half-typed on a tab they were not looking at. The form state lives in
 * settings/useSettingsForm.ts; the cards only read and write their keys.
 */
import { mdiBrain, mdiInformationOutline, mdiMicrophoneOutline, mdiShieldAccountOutline } from '@mdi/js'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { describeError } from '../errors'
import AboutTab from './settings/AboutTab.vue'
import AiTab from './settings/AiTab.vue'
import OrganisationTab from './settings/OrganisationTab.vue'
import TranscriptionTab from './settings/TranscriptionTab.vue'
import { provideSettingsForm } from './settings/useSettingsForm'
import CzSkeleton from './ui/CzSkeleton.vue'
import CzTabs from './ui/CzTabs.vue'
import { panelId, type TabItem } from './ui/tabs'

const { t } = useI18n()
const settings = provideSettingsForm()
const { summary, loadError, anyDirty } = settings

type Tab = 'transcription' | 'ai' | 'organisation' | 'about'
const TABS: readonly Tab[] = ['transcription', 'ai', 'organisation', 'about']
const TAB_PREFIX = 'citizens-settings'
const TAB_STORAGE = 'citizens.settings.tab'

function rememberedTab(): Tab {
	try {
		const stored = sessionStorage.getItem(TAB_STORAGE)
		if (stored && (TABS as readonly string[]).includes(stored)) return stored as Tab
	} catch {
		/* private window, blocked storage */
	}
	return 'transcription'
}

const tab = ref<Tab>(rememberedTab())

function selectTab(id: string): void {
	tab.value = id as Tab
	try {
		sessionStorage.setItem(TAB_STORAGE, id)
	} catch {
		/* ignore */
	}
}

const tabs = computed<TabItem[]>(() => [
	{ id: 'transcription', label: t('organizer.settings.tabs.transcription'), icon: mdiMicrophoneOutline },
	{ id: 'ai', label: t('organizer.settings.tabs.ai'), icon: mdiBrain },
	{ id: 'organisation', label: t('organizer.settings.tabs.organisation'), icon: mdiShieldAccountOutline },
	{ id: 'about', label: t('organizer.settings.tabs.about'), icon: mdiInformationOutline },
])

onMounted(async () => {
	try {
		await settings.load()
	} catch (err) {
		loadError.value = describeError(err).message
	}
})

/** Warn before a reload or a close throws away unsaved settings — the
 * backstop for a card the admin scrolled past. */
function warnIfDirty(event: BeforeUnloadEvent): void {
	if (!anyDirty.value) return
	event.preventDefault()
	event.returnValue = ''
}

onMounted(() => window.addEventListener('beforeunload', warnIfDirty))
onBeforeUnmount(() => window.removeEventListener('beforeunload', warnIfDirty))
</script>

<template>
	<div class="cz-page">
		<div class="cz-pagehead">
			<div>
				<h2>{{ t('organizer.settings.page.title') }}</h2>
				<p class="cz-muted" style="margin: 4px 0 0">
					{{ t('organizer.settings.page.lead') }}
				</p>
			</div>
		</div>

		<div v-if="loadError" class="cz-error">{{ loadError }}</div>
		<CzSkeleton v-if="!summary && !loadError" :rows="3" :height="120" />

		<template v-if="summary">
			<CzTabs :tabs="tabs" :model-value="tab" :id-prefix="TAB_PREFIX" @update:model-value="selectTab" />

			<div v-show="tab === 'transcription'" :id="panelId(TAB_PREFIX, 'transcription')" role="tabpanel">
				<TranscriptionTab />
			</div>
			<div v-show="tab === 'ai'" :id="panelId(TAB_PREFIX, 'ai')" role="tabpanel">
				<AiTab />
			</div>
			<div v-show="tab === 'organisation'" :id="panelId(TAB_PREFIX, 'organisation')" role="tabpanel">
				<OrganisationTab />
			</div>
			<!-- v-if: About asks the server for its numbers only when opened -->
			<div v-if="tab === 'about'" :id="panelId(TAB_PREFIX, 'about')" role="tabpanel">
				<AboutTab />
			</div>
		</template>
	</div>
</template>
