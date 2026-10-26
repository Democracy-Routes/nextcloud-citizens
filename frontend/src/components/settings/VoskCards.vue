<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
/**
 * Vosk as three cards: the engine (built in or a server), the model
 * manager of the built-in engine, and the model each language uses.
 */
import { mdiCheck, mdiClose, mdiDownloadOutline, mdiEngineOutline, mdiTranslate } from '@mdi/js'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import CzButton from '../ui/CzButton.vue'
import SvgIcon from '../ui/SvgIcon.vue'
import { toast } from '../ui/toast'
import SettingsCard from './SettingsCard.vue'
import { ASSEMBLY_LANGUAGES, useSettingsForm, type CardId } from './useSettingsForm'
import { failureOf, installing, percent, useVoskModels } from './useVoskModels'

const { t } = useI18n()
const settings = useSettingsForm()
const { form, testResults, busyCard } = settings
const vosk = useVoskModels()

// example values shown as placeholders, not prose — never translated
const VOSK_URL_EXAMPLE = 'ws://localhost:2700'
const VOSK_MODEL_EXAMPLE = 'vosk-model-small-it-0.22'
const VOSK_COMMAND_EXAMPLE = 'scripts/vosk-model.sh <name>'

const advanced = ref(false)
const builtin = computed(() => form.vosk_mode === 'builtin')

const engineLine = computed(() => {
	const engine = vosk.catalog.value?.engine
	if (!engine) return ''
	const state = engine.running
		? t('organizer.settings.audio.vosk.engine.running')
		: t('organizer.settings.audio.vosk.engine.stopped')
	const loaded = engine.loaded?.length
		? t('organizer.settings.audio.vosk.engine.loaded', { n: engine.loaded.length })
		: t('organizer.settings.audio.vosk.engine.none')
	const memory = vosk.memoryMb.value === null
		? t('organizer.settings.audio.vosk.models.memoryUnknown')
		: t('organizer.settings.audio.vosk.models.memory', { mb: vosk.memoryMb.value })
	return [state, loaded, memory].join(' · ')
})

async function save(card: CardId): Promise<void> {
	if (await settings.save(card)) {
		toast(t('organizer.settings.page.settingsSaved'))
		// the mode switch starts or stops the engine: show its new state
		if (card === 'voskEngine') await vosk.load()
	}
}

function cardProps(card: CardId) {
	return {
		dirty: settings.isDirty(card),
		busy: busyCard.value === card,
		error: settings.errors[card] ?? '',
	}
}
</script>

<template>
	<div>
		<SettingsCard
			:icon="mdiEngineOutline"
			:title="t('organizer.settings.audio.vosk.engine.title')"
			:lead="t('organizer.settings.audio.vosk.engine.lead')"
			test-id="card-vosk-engine"
			v-bind="cardProps('voskEngine')"
			@save="save('voskEngine')">
			<div class="cz-fieldgrid">
				<div class="cz-field" style="grid-column: span 2" data-test="vosk-mode">
					<label>{{ t('organizer.settings.audio.vosk.mode.label') }}</label>
					<div class="cz-row" style="gap: 18px">
						<label class="cz-row" style="gap: 6px; font-weight: normal">
							<input v-model="form.vosk_mode" type="radio" name="vosk-mode" value="builtin" />
							{{ t('organizer.settings.audio.vosk.mode.builtin') }}
						</label>
						<label class="cz-row" style="gap: 6px; font-weight: normal">
							<input v-model="form.vosk_mode" type="radio" name="vosk-mode" value="server" />
							{{ t('organizer.settings.audio.vosk.mode.server') }}
						</label>
					</div>
				</div>
				<div v-if="!builtin" class="cz-field" style="grid-column: span 2">
					<label>{{ t('organizer.settings.audio.vosk.url') }}</label>
					<div class="cz-row" style="flex-wrap: nowrap">
						<input v-model="form.vosk_url" type="text" style="flex: 1" :placeholder="VOSK_URL_EXAMPLE" />
						<CzButton small :disabled="busyCard !== ''" @click="settings.test('vosk', 'voskEngine')">{{ t('organizer.settings.audio.test') }}</CzButton>
					</div>
					<span v-if="testResults.vosk" class="cz-pill" :class="testResults.vosk.ok ? 'cz-pill--green' : 'cz-pill--orange'" style="text-transform: none; align-self: flex-start">
						<SvgIcon :path="testResults.vosk.ok ? mdiCheck : mdiClose" :size="14" />
						{{ testResults.vosk.message }}
					</span>
					<span class="cz-muted" style="font-size: 0.78rem">
						{{ t('organizer.settings.audio.vosk.urlHint') }}
					</span>
				</div>
				<div v-else class="cz-field" style="grid-column: span 2">
					<p v-if="engineLine" class="cz-muted" style="font-size: 0.8125rem; margin: 0" data-test="vosk-engine-line">
						{{ engineLine }}
						<span v-if="vosk.catalog.value?.engine?.last_error"> &middot; {{ vosk.catalog.value.engine.last_error }}</span>
					</p>
					<p v-if="vosk.catalogError.value" class="cz-muted" style="color: var(--cz-danger, #b00020); font-size: 0.78rem">{{ vosk.catalogError.value }}</p>
				</div>
				<div class="cz-field" style="grid-column: span 2">
					<span class="cz-muted" style="font-size: 0.78rem">
						<strong>{{ t('organizer.settings.audio.vosk.plainTitle') }}</strong>
						{{ t('organizer.settings.audio.vosk.plain') }}
					</span>
				</div>
			</div>
		</SettingsCard>

		<SettingsCard
			v-if="builtin"
			:icon="mdiDownloadOutline"
			:title="t('organizer.settings.audio.vosk.models.title')"
			:lead="t('organizer.settings.audio.vosk.models.lead')"
			:saveable="false"
			test-id="card-vosk-models">
			<div data-test="vosk-models">
				<p v-if="vosk.catalogError.value" class="cz-muted" style="color: var(--cz-danger, #b00020); font-size: 0.78rem">{{ vosk.catalogError.value }}</p>
				<template v-for="group in vosk.groups.value" :key="group.code">
					<strong style="font-size: 0.845rem; display: block; margin-top: 8px">{{ group.label }}</strong>
					<div
						v-for="row in group.rows"
						:key="row.name"
						class="cz-row cz-vosk-model"
						style="flex-wrap: nowrap; gap: 10px; padding: 3px 0"
						data-test="model-row">
						<code style="flex: 1; overflow-wrap: anywhere">{{ row.name }}</code>
						<span class="cz-pill" style="text-transform: none">{{ t('organizer.settings.audio.vosk.models.kind' + row.kind.charAt(0).toUpperCase() + row.kind.slice(1)) }}</span>
						<span class="cz-muted" style="font-size: 0.78rem; min-width: 56px">{{ t('organizer.settings.audio.vosk.models.sizeHint', { mb: row.sizeMb }) }}</span>
						<template v-if="row.installed">
							<span v-if="row.inUse" class="cz-pill cz-pill--green" style="text-transform: none">{{ t('organizer.settings.audio.vosk.models.inUse') }}</span>
							<template v-if="vosk.pendingRemove.value === row.name">
								<span style="font-size: 0.8rem">{{ t('organizer.settings.audio.vosk.models.confirmRemove', { name: row.name }) }}</span>
								<CzButton small variant="danger" data-test="model-remove-confirm" :disabled="vosk.busy.value === row.name" @click="vosk.remove(row.name)">{{ t('organizer.settings.audio.vosk.models.remove') }}</CzButton>
								<CzButton small @click="vosk.pendingRemove.value = ''">{{ t('organizer.settings.audio.vosk.models.cancel') }}</CzButton>
							</template>
							<CzButton v-else small data-test="model-remove" :disabled="row.inUse || vosk.busy.value === row.name" @click="vosk.pendingRemove.value = row.name">{{ t('organizer.settings.audio.vosk.models.remove') }}</CzButton>
						</template>
						<template v-else-if="installing(row.progress)">
							<span data-test="model-progress" style="display: flex; align-items: center; gap: 6px; min-width: 190px">
								<progress :value="percent(row.progress!)" max="100" style="flex: 1"></progress>
								<span style="font-size: 0.75rem">{{ t('organizer.settings.audio.vosk.models.phase.' + row.progress!.phase) }} {{ percent(row.progress!) }}%</span>
							</span>
							<CzButton small data-test="model-cancel" :disabled="vosk.busy.value === row.name" @click="vosk.cancel(row.name)">{{ t('organizer.settings.audio.vosk.models.cancel') }}</CzButton>
						</template>
						<template v-else>
							<span v-if="failureOf(row)" style="font-size: 0.75rem; color: var(--cz-danger, #b00020)">{{ t('organizer.settings.audio.vosk.models.phase.failed') }}: {{ failureOf(row) }}</span>
							<CzButton small data-test="model-install" :disabled="vosk.busy.value === row.name" @click="vosk.install(row.name)">{{ t('organizer.settings.audio.vosk.models.install') }}</CzButton>
						</template>
					</div>
				</template>
			</div>
		</SettingsCard>

		<SettingsCard
			:icon="mdiTranslate"
			:title="t('organizer.settings.audio.vosk.languages.title')"
			:lead="t('organizer.settings.audio.vosk.languages.lead')"
			test-id="card-vosk-languages"
			v-bind="cardProps('voskLanguages')"
			@save="save('voskLanguages')">
			<div class="cz-field">
				<i18n-t
					v-if="!builtin"
					keypath="organizer.settings.audio.vosk.perLanguageHint"
					tag="span"
					class="cz-muted"
					style="font-size: 0.78rem; margin-bottom: 10px">
					<template #name><strong>{{ t('organizer.settings.audio.vosk.perLanguageName') }}</strong></template>
					<template #command><code>{{ VOSK_COMMAND_EXAMPLE }}</code></template>
				</i18n-t>
				<div class="cz-modelhead" style="grid-template-columns: 78px 1fr 1fr">
					<span>{{ t('organizer.settings.audio.vosk.language') }}</span>
					<span>{{ t('organizer.settings.audio.liveHead') }}</span>
					<span>{{ t('organizer.settings.audio.finalHead') }}</span>
				</div>
				<div
					v-for="lang in ASSEMBLY_LANGUAGES"
					:key="lang.code"
					class="cz-modelrow"
					style="grid-template-columns: 78px 1fr 1fr; margin-bottom: 6px">
					<span style="font-size: 0.845rem; align-self: center">{{ lang.label }}</span>
					<select
						v-if="builtin"
						v-model="form.vosk_language_models[lang.code].live"
						:aria-label="t('organizer.settings.audio.vosk.liveModelFor', { language: lang.label })">
						<option value="">{{ t('organizer.settings.audio.vosk.notConfigured') }}</option>
						<option v-for="m in vosk.choices(lang.code, form.vosk_language_models[lang.code].live)" :key="m.name" :value="m.name">
							{{ m.name }}{{ m.missing ? ' (' + t('organizer.settings.audio.vosk.models.notInstalled') + ')' : '' }}
						</option>
					</select>
					<input
						v-else
						v-model="form.vosk_language_models[lang.code].live"
						type="text"
						:placeholder="t('organizer.settings.audio.vosk.notConfigured')"
						:aria-label="t('organizer.settings.audio.vosk.liveModelFor', { language: lang.label })" />
					<select
						v-if="builtin"
						v-model="form.vosk_language_models[lang.code].final"
						:aria-label="t('organizer.settings.audio.vosk.finalModelFor', { language: lang.label })">
						<option value="">{{ t('organizer.settings.audio.vosk.sameAsLive') }}</option>
						<option v-for="m in vosk.choices(lang.code, form.vosk_language_models[lang.code].final)" :key="m.name" :value="m.name">
							{{ m.name }}{{ m.missing ? ' (' + t('organizer.settings.audio.vosk.models.notInstalled') + ')' : '' }}
						</option>
					</select>
					<input
						v-else
						v-model="form.vosk_language_models[lang.code].final"
						type="text"
						:placeholder="t('organizer.settings.audio.vosk.sameAsLive')"
						:aria-label="t('organizer.settings.audio.vosk.finalModelFor', { language: lang.label })" />
				</div>
				<span class="cz-muted" style="font-size: 0.78rem; margin-top: 6px">
					{{ t('organizer.settings.audio.vosk.blankHint') }}
				</span>
			</div>
			<CzButton variant="tertiary" small style="margin-top: 8px" data-test="vosk-advanced" @click="advanced = !advanced">
				{{ advanced ? t('organizer.settings.audio.vosk.advancedHide') : t('organizer.settings.audio.vosk.advanced') }}
			</CzButton>
			<div v-if="advanced" class="cz-field" style="margin-top: 8px; max-width: 420px">
				<label>{{ t('organizer.settings.audio.vosk.label') }}</label>
				<input v-model="form.vosk_batch_model" type="text" :placeholder="VOSK_MODEL_EXAMPLE" />
				<span class="cz-muted" style="font-size: 0.78rem">
					{{ t('organizer.settings.audio.vosk.labelHint') }}
				</span>
			</div>
		</SettingsCard>
	</div>
</template>
