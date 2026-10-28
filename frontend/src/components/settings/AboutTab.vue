<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
/** The About tab: read-only facts about this installation. */
import { mdiBookOpenOutline, mdiDatabaseOutline, mdiInformationOutline, mdiMicrophoneOutline } from '@mdi/js'
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../../api'
import { auth } from '../../auth'
import { describeError } from '../../errors'
import type { AboutInfo } from '../../types'
import SettingsCard from './SettingsCard.vue'

const { t } = useI18n()
const info = ref<AboutInfo | null>(null)
const error = ref('')

const DOCS = 'https://github.com/Democracy-Routes/nextcloud-citizens/blob/main/docs'
const docLinks = [
	{ href: `${DOCS}/administration.md`, key: 'adminGuide' },
	{ href: `${DOCS}/facilitator-guide.md`, key: 'facilitatorGuide' },
	{ href: `${DOCS}/event-checklist.md`, key: 'checklist' },
	{ href: `${DOCS}/privacy.md`, key: 'privacy' },
]

onMounted(async () => {
	try {
		info.value = await api.about()
	} catch (err) {
		error.value = describeError(err).message
	}
})

function inUse(data: AboutInfo): string {
	const names = Object.entries(data.engine.in_use)
		.filter(([, count]) => count > 0)
		.map(([name]) => name)
	return names.length ? names.join(', ') : t('organizer.settings.about.none')
}

function memory(bytes: number | null): string {
	return bytes === null
		? t('organizer.settings.about.unknown')
		: t('organizer.settings.about.mb', { mb: Math.floor(bytes / 1048576) })
}

function when(iso: string | null): string {
	return iso ? new Date(iso).toLocaleString() : ''
}
</script>

<template>
	<div class="cz-settings-column">
		<SettingsCard
			:icon="mdiInformationOutline"
			:title="t('organizer.settings.about.versionTitle')"
			:lead="t('organizer.settings.about.versionLead')"
			:saveable="false"
			:error="error"
			test-id="about-version">
			<p v-if="!info && !error" class="cz-muted">{{ t('organizer.settings.about.loading') }}</p>
			<dl v-else-if="info" class="cz-about">
				<dt>{{ t('organizer.settings.about.version') }}</dt>
				<dd>{{ info.version }}</dd>
				<dt>{{ t('organizer.settings.about.schema') }}</dt>
				<dd>{{ info.schema_revision ?? t('organizer.settings.about.unknown') }}</dd>
				<template v-if="auth.config">
					<dt>{{ t('organizer.settings.about.runMode') }}</dt>
					<dd data-test="about-run-mode">
						{{ auth.config.mode === 'standalone' ? t('organizer.settings.about.runStandalone') : t('organizer.settings.about.runNextcloud') }}
					</dd>
					<template v-if="auth.config.mode === 'standalone'">
						<dt>{{ t('organizer.settings.about.signIn') }}</dt>
						<dd>{{ auth.config.login.oidc ? t('organizer.settings.about.signInPasswordOidc') : t('organizer.settings.about.signInPassword') }}</dd>
						<dt>{{ t('organizer.settings.about.mail') }}</dt>
						<dd>{{ auth.config.mail ? t('organizer.settings.about.mailConfigured') : t('organizer.settings.about.mailNotConfigured') }}</dd>
					</template>
				</template>
			</dl>
		</SettingsCard>

		<SettingsCard
			:icon="mdiMicrophoneOutline"
			:title="t('organizer.settings.about.engineTitle')"
			:lead="t('organizer.settings.about.engineLead')"
			:saveable="false"
			test-id="about-engine">
			<p v-if="!info && !error" class="cz-muted">{{ t('organizer.settings.about.loading') }}</p>
			<dl v-else-if="info" class="cz-about">
				<dt>{{ t('organizer.settings.about.provider') }}</dt>
				<dd>{{ info.stt_provider ?? '—' }}</dd>
				<dt>{{ t('organizer.settings.about.mode') }}</dt>
				<dd>{{ info.vosk_mode === 'builtin' ? t('organizer.settings.about.modeBuiltin') : t('organizer.settings.about.modeServer') }}</dd>
				<dt>{{ t('organizer.settings.about.state') }}</dt>
				<dd>{{ info.engine.running ? t('organizer.settings.about.running') : t('organizer.settings.about.stopped') }}</dd>
				<dt>{{ t('organizer.settings.about.loaded') }}</dt>
				<dd>{{ info.engine.loaded.length ? info.engine.loaded.join(', ') : t('organizer.settings.about.none') }}</dd>
				<dt>{{ t('organizer.settings.about.inUse') }}</dt>
				<dd>{{ inUse(info) }}</dd>
				<dt>{{ t('organizer.settings.about.memory') }}</dt>
				<dd>{{ memory(info.engine.memory_available_bytes) }}</dd>
				<template v-if="info.engine.last_error">
					<dt>{{ t('organizer.settings.about.lastError') }}</dt>
					<dd>{{ info.engine.last_error }}</dd>
				</template>
			</dl>
		</SettingsCard>

		<SettingsCard
			:icon="mdiDatabaseOutline"
			:title="t('organizer.settings.about.storageTitle')"
			:lead="t('organizer.settings.about.storageLead')"
			:saveable="false"
			test-id="about-storage">
			<p v-if="!info && !error" class="cz-muted">{{ t('organizer.settings.about.loading') }}</p>
			<dl v-else-if="info" class="cz-about">
				<dt>{{ t('organizer.settings.about.diskFree') }}</dt>
				<dd>{{ info.disk_free_gb === null ? t('organizer.settings.about.unknown') : t('organizer.settings.about.gb', { gb: info.disk_free_gb }) }}</dd>
				<dt>{{ t('organizer.settings.about.storage') }}</dt>
				<dd>{{ info.storage_ok ? t('organizer.settings.about.storageOk') : t('organizer.settings.about.storageError') }}</dd>
				<dt>{{ t('organizer.settings.about.queued') }}</dt>
				<dd>{{ info.jobs.queued }}</dd>
				<dt>{{ t('organizer.settings.about.jobsRunning') }}</dt>
				<dd>{{ info.jobs.running }}</dd>
				<dt>{{ t('organizer.settings.about.retry') }}</dt>
				<dd>{{ info.jobs.retry }}</dd>
				<dt>{{ t('organizer.settings.about.failed') }}</dt>
				<dd>{{ info.jobs.failed }}</dd>
				<template v-if="info.jobs.newest_failure">
					<dt>{{ t('organizer.settings.about.newestFailure') }}</dt>
					<dd>
						{{ info.jobs.newest_failure.type }}: {{ info.jobs.newest_failure.last_error }}
						<span v-if="info.jobs.newest_failure.updated_at" class="cz-muted">
							{{ when(info.jobs.newest_failure.updated_at) }}
						</span>
					</dd>
				</template>
				<dt>{{ t('organizer.settings.about.lastSweep') }}</dt>
				<dd>{{ info.last_sweep_at ? when(info.last_sweep_at) : t('organizer.settings.about.never') }}</dd>
			</dl>
		</SettingsCard>

		<SettingsCard
			:icon="mdiBookOpenOutline"
			:title="t('organizer.settings.about.docsTitle')"
			:lead="t('organizer.settings.about.docsLead')"
			:saveable="false"
			test-id="about-docs">
			<ul class="cz-about-links">
				<li v-for="link in docLinks" :key="link.key">
					<a :href="link.href" target="_blank" rel="noopener">{{ t(`organizer.settings.about.${link.key}`) }}</a>
				</li>
			</ul>
			<p class="cz-muted">{{ t('organizer.settings.about.deviceReportHint') }}</p>
		</SettingsCard>
	</div>
</template>
