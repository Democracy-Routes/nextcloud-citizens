<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
/** The Organisation tab: who is responsible for the data, retention, branding. */
import { mdiDeleteClockOutline, mdiImageOutline, mdiShieldAccountOutline } from '@mdi/js'
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { api, BASE } from '../../api'
import CzButton from '../ui/CzButton.vue'
import { toast } from '../ui/toast'
import SettingsCard from './SettingsCard.vue'
import { useSettingsForm, type CardId } from './useSettingsForm'

const { t } = useI18n()
const settings = useSettingsForm()
const { form, summary, errors, busyCard } = settings

const ORG_ADDRESS_EXAMPLE = 'Piazza Maggiore 6, 40124 Bologna'
const ORG_CONTACT_EMAIL_EXAMPLE = 'privacy@example.org'
const ORG_AUTHORITY_EXAMPLE = 'Garante per la protezione dei dati personali'
const ORG_NAME_EXAMPLE = 'Democracy Innovators'

const logoSet = ref(summary.value?.logo_set ?? false)
const logoVersion = ref(0)
const logoError = ref('')
const logoBusy = ref(false)
watch(
	() => summary.value?.logo_set,
	(value) => {
		if (value !== undefined) logoSet.value = value
	},
)

async function save(card: CardId): Promise<void> {
	if (await settings.save(card)) toast(t('organizer.settings.page.settingsSaved'))
}

function logoUrl(): string {
	return `${BASE}/api/v1/admin/logo?v=${logoVersion.value}`
}

async function uploadLogo(event: Event): Promise<void> {
	const input = event.target as HTMLInputElement
	const file = input.files?.[0]
	input.value = ''
	if (!file) return
	if (file.size > 1_000_000) {
		logoError.value = t('organizer.settings.branding.tooLarge')
		return
	}
	logoBusy.value = true
	logoError.value = ''
	try {
		const buffer = await file.arrayBuffer()
		let binary = ''
		for (const byte of new Uint8Array(buffer)) binary += String.fromCharCode(byte)
		await api.uploadLogo(btoa(binary))
		logoSet.value = true
		logoVersion.value += 1
		toast(t('organizer.settings.branding.logoSaved'))
	} catch (err) {
		logoError.value = err instanceof Error ? err.message : String(err)
	} finally {
		logoBusy.value = false
	}
}

async function removeLogo(): Promise<void> {
	logoBusy.value = true
	logoError.value = ''
	try {
		await api.deleteLogo()
		logoSet.value = false
		toast(t('organizer.settings.branding.logoRemoved'))
	} catch (err) {
		logoError.value = err instanceof Error ? err.message : String(err)
	} finally {
		logoBusy.value = false
	}
}
</script>

<template>
	<div v-if="summary" class="cz-settings-column">
		<SettingsCard
			:icon="mdiShieldAccountOutline"
			:title="t('organizer.settings.org.title')"
			test-id="card-org"
			:lead="t('organizer.settings.org.lead')"
			:dirty="settings.isDirty('org')"
			:busy="busyCard === 'org'"
			:error="errors.org"
			@save="save('org')">
			<div class="cz-field" style="max-width: 420px">
				<label>{{ t('organizer.settings.org.controller') }}</label>
				<input
					v-model="form.consent_controller"
					type="text"
					:placeholder="form.organization_name || t('organizer.settings.org.controllerPlaceholder')" />
				<p class="cz-muted" style="font-size: 0.78rem; margin-top: 6px">
					{{ t('organizer.settings.org.controllerHint') }}
				</p>
			</div>
			<div class="cz-field" style="max-width: 420px">
				<label>{{ t('organizer.settings.org.address') }}</label>
				<input v-model="form.org_address" type="text" :placeholder="ORG_ADDRESS_EXAMPLE" />
			</div>
			<div class="cz-field" style="max-width: 420px">
				<label>{{ t('organizer.settings.org.contact') }}</label>
				<input v-model="form.consent_contact" type="text" :placeholder="ORG_CONTACT_EMAIL_EXAMPLE" />
			</div>
			<div class="cz-field" style="max-width: 420px">
				<label>{{ t('organizer.settings.org.dpo') }}</label>
				<input v-model="form.org_dpo" type="text" :placeholder="t('organizer.settings.org.dpoPlaceholder')" />
			</div>
			<div class="cz-field" style="max-width: 420px">
				<label>{{ t('organizer.settings.org.hosting') }}</label>
				<input v-model="form.org_hosting" type="text" :placeholder="t('organizer.settings.org.hostingPlaceholder')" />
				<p class="cz-muted" style="font-size: 0.78rem; margin-top: 6px">
					{{ t('organizer.settings.org.hostingHint') }}
				</p>
			</div>
			<div class="cz-field" style="max-width: 420px">
				<label>{{ t('organizer.settings.org.authority') }}</label>
				<input v-model="form.org_authority" type="text" :placeholder="ORG_AUTHORITY_EXAMPLE" />
				<p class="cz-muted" style="font-size: 0.78rem; margin-top: 6px">
					{{ t('organizer.settings.org.authorityHint') }}
				</p>
			</div>
		</SettingsCard>

		<SettingsCard
			:icon="mdiDeleteClockOutline"
			:title="t('organizer.settings.retention.title')"
			test-id="card-retention"
			:dirty="settings.isDirty('retention')"
			:busy="busyCard === 'retention'"
			:error="errors.retention"
			@save="save('retention')">
			<i18n-t
				keypath="organizer.settings.retention.lead"
				tag="p"
				class="cz-muted"
				style="font-size: 0.845rem; margin-bottom: 14px">
				<template #closed><strong>{{ t('organizer.settings.retention.closed') }}</strong></template>
			</i18n-t>
			<div class="cz-field" style="max-width: 260px">
				<label>{{ t('organizer.settings.retention.days') }}</label>
				<input v-model.number="form.audio_retention_days" type="number" min="0" max="3650" />
				<p class="cz-muted" style="font-size: 0.78rem; margin-top: 6px">
					{{
						Number(form.audio_retention_days) > 0
							? t('organizer.settings.retention.deletedAfter', { days: form.audio_retention_days })
							: t('organizer.settings.retention.keptForever')
					}}
				</p>
			</div>
		</SettingsCard>

		<SettingsCard
			:icon="mdiImageOutline"
			:title="t('organizer.settings.branding.title')"
			test-id="card-branding"
			:lead="t('organizer.settings.branding.lead')"
			:dirty="settings.isDirty('branding')"
			:busy="busyCard === 'branding'"
			:error="errors.branding || logoError"
			@save="save('branding')">
			<div class="cz-field" style="max-width: 420px">
				<label>{{ t('organizer.settings.branding.name') }}</label>
				<input v-model="form.organization_name" type="text" :placeholder="ORG_NAME_EXAMPLE" />
			</div>
			<div class="cz-row" style="align-items: center; gap: 16px">
				<img
					v-if="logoSet"
					:src="logoUrl()"
					:alt="t('organizer.settings.branding.logoAlt')"
					style="max-height: 56px; max-width: 200px; border: 1px solid var(--cz-border); border-radius: 8px; padding: 6px; background: #fff" />
				<label class="cz-btn cz-btn--secondary" style="cursor: pointer">
					{{ logoSet ? t('organizer.settings.branding.replaceLogo') : t('organizer.settings.branding.uploadLogo') }}
					<input type="file" accept="image/png,image/jpeg" style="display: none" @change="uploadLogo" />
				</label>
				<CzButton v-if="logoSet" small variant="tertiary" :disabled="logoBusy" @click="removeLogo">
					{{ t('organizer.settings.branding.remove') }}
				</CzButton>
			</div>
		</SettingsCard>
	</div>
</template>
