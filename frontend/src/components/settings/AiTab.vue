<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
/** The AI tab: transcript analysis and the AI facilitator, one card each. */
import { mdiAccountVoice, mdiBrain, mdiCheck, mdiClose } from '@mdi/js'
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import CzButton from '../ui/CzButton.vue'
import SvgIcon from '../ui/SvgIcon.vue'
import { toast } from '../ui/toast'
import SettingsCard from './SettingsCard.vue'
import { FACILITATOR_LEVELS, useSettingsForm, type CardId } from './useSettingsForm'

const { t } = useI18n()
const settings = useSettingsForm()
const { form, secrets, summary, testResults, errors, busyCard } = settings

const ANALYSIS_BASE_URL_EXAMPLE = 'https://api.mistral.ai/v1'
const showPrompts = ref(false)
const facAdvanced = ref(false)

async function save(card: CardId): Promise<void> {
	if (await settings.save(card)) toast(t('organizer.settings.page.settingsSaved'))
}

function keyPlaceholder(configured: boolean, hint: string): string {
	return configured
		? t('organizer.settings.audio.keyConfigured', { hint })
		: t('organizer.settings.audio.pasteKey')
}
</script>

<template>
	<div v-if="summary" class="cz-settings-column">
		<SettingsCard
			:icon="mdiBrain"
			:title="t('organizer.settings.ai.title')"
			test-id="card-analysis"
			:lead="t('organizer.settings.ai.lead')"
			:dirty="settings.isDirty('analysis')"
			:busy="busyCard === 'analysis'"
			:error="errors.analysis"
			@save="save('analysis')">
			<label style="display: flex; align-items: center; gap: 8px; cursor: pointer; margin-bottom: 14px">
				<input v-model="form.analysis_enabled" type="checkbox" />
				{{ t('organizer.settings.ai.auto') }}
			</label>
			<div class="cz-fieldgrid">
				<div class="cz-field" style="grid-column: span 2">
					<label>{{ t('organizer.settings.ai.baseUrl') }}</label>
					<input v-model="form.analysis_base_url" type="text" :placeholder="ANALYSIS_BASE_URL_EXAMPLE" />
				</div>
				<div class="cz-field">
					<label>{{ t('organizer.settings.ai.model') }}</label>
					<input v-model="form.analysis_model" type="text" placeholder="mistral-large-latest" />
				</div>
				<div class="cz-field">
					<label>{{ t('organizer.settings.ai.key') }}</label>
					<div class="cz-row" style="flex-wrap: nowrap">
						<input
							v-model="secrets.analysis_api_key"
							type="password"
							autocomplete="off"
							style="flex: 1"
							:placeholder="keyPlaceholder(summary.analysis.configured, summary.analysis.key_hint)" />
						<CzButton small :disabled="busyCard !== ''" @click="settings.test('analysis', 'analysis')">
							{{ t('organizer.settings.audio.test') }}
						</CzButton>
					</div>
					<span
						v-if="testResults.analysis"
						class="cz-pill"
						:class="testResults.analysis.ok ? 'cz-pill--green' : 'cz-pill--orange'"
						style="text-transform: none; align-self: flex-start">
						<SvgIcon :path="testResults.analysis.ok ? mdiCheck : mdiClose" :size="14" />
						{{ testResults.analysis.message }}
					</span>
				</div>
			</div>

			<div class="cz-field" style="margin-top: 12px">
				<label>{{ t('organizer.settings.ai.extra') }}</label>
				<textarea
					v-model="form.analysis_extra_instructions"
					rows="4"
					:placeholder="t('organizer.settings.ai.extraPlaceholder')"></textarea>
				<span class="cz-muted" style="font-size: 0.78rem">
					{{ t('organizer.settings.ai.extraHint') }}
				</span>
			</div>

			<button
				type="button"
				class="cz-linklike"
				style="background: none; border: none; padding: 0; color: var(--cz-primary); cursor: pointer; font-size: 0.8125rem"
				@click="showPrompts = !showPrompts">
				{{ showPrompts ? t('organizer.settings.ai.hidePrompts') : t('organizer.settings.ai.showPrompts') }}
			</button>
			<div v-if="showPrompts && summary.analysis.default_prompts" style="margin-top: 10px">
				<p class="cz-muted" style="font-size: 0.75rem; margin-bottom: 4px">{{ t('organizer.settings.ai.tablePrompt') }}</p>
				<pre class="cz-promptbox">{{ summary.analysis.default_prompts.table }}</pre>
				<p class="cz-muted" style="font-size: 0.75rem; margin: 10px 0 4px">{{ t('organizer.settings.ai.roundPrompt') }}</p>
				<pre class="cz-promptbox">{{ summary.analysis.default_prompts.round }}</pre>
			</div>
		</SettingsCard>

		<SettingsCard
			:icon="mdiAccountVoice"
			:title="t('organizer.settings.facilitator.title')"
			test-id="card-facilitator"
			:lead="t('organizer.settings.facilitator.lead')"
			:dirty="settings.isDirty('facilitator')"
			:busy="busyCard === 'facilitator'"
			:error="errors.facilitator"
			@save="save('facilitator')">
			<div class="cz-field" data-test="facilitator-level">
				<label>{{ t('organizer.settings.facilitator.level') }}</label>
				<div class="cz-row" style="gap: 14px; flex-wrap: wrap">
					<label v-for="level in FACILITATOR_LEVELS" :key="level" style="display: flex; align-items: center; gap: 6px; cursor: pointer">
						<input v-model="form.facilitator_level" type="radio" :value="level" />
						{{ t(`organizer.settings.facilitator.levels.${level}`) }}
					</label>
				</div>
			</div>
			<div class="cz-fieldgrid" style="margin-top: 10px">
				<div class="cz-field" style="grid-column: span 2">
					<label>{{ t('organizer.settings.facilitator.baseUrl') }}</label>
					<input v-model="form.facilitator_base_url" type="text" :placeholder="form.analysis_base_url || 'https://api.mistral.ai/v1'" />
				</div>
				<div class="cz-field">
					<label>{{ t('organizer.settings.facilitator.model') }}</label>
					<input v-model="form.facilitator_model" type="text" :placeholder="form.analysis_model || 'mistral-small-latest'" />
				</div>
				<div class="cz-field">
					<label>{{ t('organizer.settings.facilitator.key') }}</label>
					<div class="cz-row" style="flex-wrap: nowrap">
						<input
							v-model="secrets.facilitator_api_key"
							type="password"
							autocomplete="off"
							style="flex: 1"
							:placeholder="keyPlaceholder(summary.facilitator?.own_key ?? false, summary.facilitator?.key_hint ?? '')" />
						<CzButton
							small
							:disabled="busyCard !== ''"
							data-test="test-facilitator"
							@click="settings.test('facilitator', 'facilitator')">
							{{ t('organizer.settings.audio.test') }}
						</CzButton>
					</div>
					<span
						v-if="testResults.facilitator"
						class="cz-pill"
						:class="testResults.facilitator.ok ? 'cz-pill--green' : 'cz-pill--orange'"
						style="text-transform: none; align-self: flex-start">
						<SvgIcon :path="testResults.facilitator.ok ? mdiCheck : mdiClose" :size="14" />
						{{ testResults.facilitator.message }}
					</span>
				</div>
			</div>
			<CzButton variant="tertiary" small style="margin-top: 8px" @click="facAdvanced = !facAdvanced">
				{{ facAdvanced ? t('organizer.settings.facilitator.hideThresholds') : t('organizer.settings.facilitator.showThresholds') }}
			</CzButton>
			<div v-if="facAdvanced" class="cz-fieldgrid" style="margin-top: 8px" data-test="facilitator-thresholds">
				<div class="cz-field">
					<label>{{ t('organizer.settings.facilitator.interval') }}</label>
					<input v-model.number="form.facilitator_interval_minutes" type="number" min="1" max="60" />
				</div>
				<div class="cz-field">
					<label>{{ t('organizer.settings.facilitator.dominance') }}</label>
					<input v-model.number="form.facilitator_dominance_percent" type="number" min="40" max="95" />
				</div>
				<div class="cz-field">
					<label>{{ t('organizer.settings.facilitator.silence') }}</label>
					<input v-model.number="form.facilitator_silence_seconds" type="number" min="20" max="600" />
				</div>
			</div>
		</SettingsCard>
	</div>
</template>
