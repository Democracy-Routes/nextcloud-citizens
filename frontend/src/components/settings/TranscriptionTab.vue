<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
/**
 * Transcription: the service, the selected provider's own card, the Vosk
 * cards when Vosk is the service, and the limits of the selected service.
 */
import { mdiCheck, mdiClose, mdiKeyOutline, mdiMicrophoneOutline, mdiSpeedometer } from '@mdi/js'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { SttProvider } from '../../types'
import CzButton from '../ui/CzButton.vue'
import SvgIcon from '../ui/SvgIcon.vue'
import { toast } from '../ui/toast'
import SettingsCard from './SettingsCard.vue'
import { STT_PROVIDERS, useSettingsForm, type CardId } from './useSettingsForm'
import VoskCards from './VoskCards.vue'

const { t } = useI18n()
const settings = useSettingsForm()
const { form, secrets, summary, testResults, busyCard } = settings

// example values shown as placeholders, not prose — never translated
const DEEPGRAM_ENDPOINT_EXAMPLE = 'wss://api.deepgram.com/v1/listen'
const WHISPER_BASE_URL_EXAMPLE = 'https://api.openai.com/v1'

const providerLabel = computed<Record<SttProvider, string>>(() => ({
	mistral: t('organizer.settings.providers.mistral'),
	deepgram: t('organizer.settings.providers.deepgram'),
	whisper: t('organizer.settings.providers.whisper'),
	vosk: t('organizer.settings.providers.vosk'),
}))

// every engine produces live captions, each through its own protocol
const captionNote = computed<Record<SttProvider, string>>(() => ({
	deepgram: t('organizer.settings.captionNote.deepgram'),
	mistral: t('organizer.settings.captionNote.mistral'),
	whisper: t('organizer.settings.captionNote.whisper'),
	vosk: t('organizer.settings.captionNote.vosk'),
}))

const selected = computed(() => form.stt_provider)

function keyPlaceholder(configured: boolean, hint: string): string {
	return configured
		? t('organizer.settings.audio.keyConfigured', { hint })
		: t('organizer.settings.audio.pasteKey')
}

async function save(card: CardId): Promise<void> {
	if (await settings.save(card)) toast(t('organizer.settings.page.settingsSaved'))
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
			:icon="mdiMicrophoneOutline"
			:title="t('organizer.settings.audio.title')"
			:lead="t('organizer.settings.audio.serviceLead')"
			test-id="card-service"
			v-bind="cardProps('service')"
			@save="save('service')">
			<div class="cz-row" style="margin-bottom: 14px">
				<label
					v-for="provider in STT_PROVIDERS"
					:key="provider"
					class="cz-radiocard"
					:class="{ 'cz-radiocard--checked': form.stt_provider === provider }">
					<input v-model="form.stt_provider" type="radio" :value="provider" />
					<SvgIcon v-if="form.stt_provider === provider" :path="mdiCheck" :size="16" />
					{{ providerLabel[provider] }}
				</label>
			</div>
			<p class="cz-muted" style="font-size: 0.8125rem; margin: -6px 0 14px">
				{{ captionNote[selected] }}
				{{ t('organizer.settings.audio.provisional') }}
			</p>
			<div class="cz-row" style="gap: 24px; margin-top: 4px">
				<label style="display: flex; align-items: center; gap: 8px; cursor: pointer">
					<input v-model="form.stt_live_enabled" type="checkbox" /> {{ t('organizer.settings.audio.liveHead') }}
				</label>
				<label style="display: flex; align-items: center; gap: 8px; cursor: pointer">
					<input v-model="form.stt_batch_enabled" type="checkbox" /> {{ t('organizer.settings.audio.finalHead') }}
				</label>
			</div>
			<span class="cz-muted" style="font-size: 0.78rem; display: block; margin-top: 8px">
				<template v-if="form.stt_live_enabled && form.stt_batch_enabled">
					{{ t('organizer.settings.audio.modes.both') }}
				</template>
				<template v-else-if="form.stt_batch_enabled">
					{{ t('organizer.settings.audio.modes.finalOnly') }}
				</template>
				<template v-else-if="form.stt_live_enabled">
					<strong>{{ t('organizer.settings.audio.modes.liveOnlyTitle') }}</strong>
					{{ t('organizer.settings.audio.modes.liveOnly') }}
				</template>
				<template v-else>
					<strong style="color: var(--cz-danger)">{{ t('organizer.settings.audio.modes.noneTitle') }}</strong>
					{{ t('organizer.settings.audio.modes.none') }}
				</template>
			</span>
		</SettingsCard>

		<!-- the selected provider's own card; Vosk has its own set below -->
		<SettingsCard
			v-if="selected === 'mistral' && summary"
			:icon="mdiKeyOutline"
			:title="providerLabel.mistral"
			test-id="card-mistral"
			v-bind="cardProps('mistral')"
			@save="save('mistral')">
			<div class="cz-fieldgrid">
				<div class="cz-field">
					<label>{{ t('organizer.settings.audio.mistral.key') }}</label>
					<div class="cz-row" style="flex-wrap: nowrap">
						<input
							v-model="secrets.mistral_api_key"
							type="password"
							autocomplete="off"
							style="flex: 1"
							:placeholder="keyPlaceholder(summary.stt.mistral_configured, summary.stt.mistral_key_hint)" />
						<CzButton small :disabled="busyCard !== ''" @click="settings.test('mistral', 'mistral')">{{ t('organizer.settings.audio.test') }}</CzButton>
					</div>
					<span v-if="testResults.mistral" class="cz-pill" :class="testResults.mistral.ok ? 'cz-pill--green' : 'cz-pill--orange'" style="text-transform: none; align-self: flex-start">
						<SvgIcon :path="testResults.mistral.ok ? mdiCheck : mdiClose" :size="14" />
						{{ testResults.mistral.message }}
					</span>
				</div>
				<div class="cz-field" style="grid-column: span 2">
					<div class="cz-modelhead">
						<span>{{ t('organizer.settings.audio.liveHead') }}</span>
						<span>{{ t('organizer.settings.audio.finalHead') }}</span>
					</div>
					<div class="cz-modelrow">
						<input v-model="form.mistral_live_model" type="text" placeholder="voxtral-mini-transcribe-realtime-2602" :aria-label="t('organizer.settings.audio.liveModelAria')" />
						<input v-model="form.mistral_batch_model" type="text" placeholder="voxtral-mini-latest" :aria-label="t('organizer.settings.audio.finalModelAria')" />
					</div>
					<div class="cz-modelhead cz-modelhead--hint">
						<span>{{ t('organizer.settings.audio.mistral.liveHint') }}</span>
						<span>{{ t('organizer.settings.audio.finalHint') }}</span>
					</div>
				</div>
			</div>
		</SettingsCard>

		<SettingsCard
			v-else-if="selected === 'deepgram' && summary"
			:icon="mdiKeyOutline"
			:title="providerLabel.deepgram"
			test-id="card-deepgram"
			v-bind="cardProps('deepgram')"
			@save="save('deepgram')">
			<div class="cz-fieldgrid">
				<div class="cz-field">
					<label>{{ t('organizer.settings.audio.deepgram.key') }}</label>
					<div class="cz-row" style="flex-wrap: nowrap">
						<input
							v-model="secrets.deepgram_api_key"
							type="password"
							autocomplete="off"
							style="flex: 1"
							:placeholder="keyPlaceholder(summary.stt.deepgram_configured, summary.stt.deepgram_key_hint)" />
						<CzButton small :disabled="busyCard !== ''" @click="settings.test('deepgram', 'deepgram')">{{ t('organizer.settings.audio.test') }}</CzButton>
					</div>
					<span v-if="testResults.deepgram" class="cz-pill" :class="testResults.deepgram.ok ? 'cz-pill--green' : 'cz-pill--orange'" style="text-transform: none; align-self: flex-start">
						<SvgIcon :path="testResults.deepgram.ok ? mdiCheck : mdiClose" :size="14" />
						{{ testResults.deepgram.message }}
					</span>
				</div>
				<div class="cz-field" style="grid-column: span 2">
					<div class="cz-modelhead">
						<span>{{ t('organizer.settings.audio.liveHead') }}</span>
						<span>{{ t('organizer.settings.audio.finalHead') }}</span>
					</div>
					<div class="cz-modelrow">
						<input v-model="form.deepgram_live_model" type="text" placeholder="nova-3" :aria-label="t('organizer.settings.audio.liveModelAria')" />
						<input v-model="form.deepgram_batch_model" type="text" placeholder="nova-3" :aria-label="t('organizer.settings.audio.finalModelAria')" />
					</div>
					<div class="cz-modelhead cz-modelhead--hint">
						<span>{{ t('organizer.settings.audio.deepgram.liveHint') }}</span>
						<span>{{ t('organizer.settings.audio.finalHint') }}</span>
					</div>
				</div>
				<div class="cz-field" style="grid-column: span 2">
					<label>{{ t('organizer.settings.audio.deepgram.endpoint') }}</label>
					<input v-model="form.deepgram_live_url" type="text" :placeholder="DEEPGRAM_ENDPOINT_EXAMPLE" />
					<span class="cz-muted" style="font-size: 0.78rem">
						{{ t('organizer.settings.audio.deepgram.endpointHint') }}
					</span>
				</div>
			</div>
		</SettingsCard>

		<SettingsCard
			v-else-if="selected === 'whisper' && summary"
			:icon="mdiKeyOutline"
			:title="providerLabel.whisper"
			test-id="card-whisper"
			v-bind="cardProps('whisper')"
			@save="save('whisper')">
			<div class="cz-fieldgrid">
				<div class="cz-field" style="grid-column: span 2">
					<label>{{ t('organizer.settings.audio.whisper.baseUrl') }}</label>
					<input v-model="form.whisper_base_url" type="text" :placeholder="WHISPER_BASE_URL_EXAMPLE" />
					<span class="cz-muted" style="font-size: 0.78rem">
						{{ t('organizer.settings.audio.whisper.baseUrlHint') }}
					</span>
				</div>
				<div class="cz-field" style="grid-column: span 2">
					<div class="cz-modelhead">
						<span>{{ t('organizer.settings.audio.liveHead') }}</span>
						<span>{{ t('organizer.settings.audio.finalHead') }}</span>
					</div>
					<div class="cz-modelrow">
						<input v-model="form.whisper_live_model" type="text" :placeholder="t('organizer.settings.audio.whisper.sameAsFinal')" :aria-label="t('organizer.settings.audio.liveModelAria')" />
						<input v-model="form.whisper_batch_model" type="text" placeholder="whisper-1" :aria-label="t('organizer.settings.audio.finalModelAria')" />
					</div>
					<div class="cz-modelhead cz-modelhead--hint">
						<span>{{ t('organizer.settings.audio.whisper.liveHint') }}</span>
						<span>{{ t('organizer.settings.audio.whisper.finalHint') }}</span>
					</div>
				</div>
				<div class="cz-field">
					<label>{{ t('organizer.settings.audio.whisper.key') }}</label>
					<div class="cz-row" style="flex-wrap: nowrap">
						<input
							v-model="secrets.whisper_api_key"
							type="password"
							autocomplete="off"
							style="flex: 1"
							:placeholder="keyPlaceholder(summary.stt.whisper_configured, summary.stt.whisper_key_hint)" />
						<CzButton small :disabled="busyCard !== ''" @click="settings.test('whisper', 'whisper')">{{ t('organizer.settings.audio.test') }}</CzButton>
					</div>
					<span v-if="testResults.whisper" class="cz-pill" :class="testResults.whisper.ok ? 'cz-pill--green' : 'cz-pill--orange'" style="text-transform: none; align-self: flex-start">
						<SvgIcon :path="testResults.whisper.ok ? mdiCheck : mdiClose" :size="14" />
						{{ testResults.whisper.message }}
					</span>
					<span class="cz-muted" style="font-size: 0.78rem">
						{{ t('organizer.settings.audio.whisper.keyHint') }}
					</span>
				</div>
				<div class="cz-field" style="grid-column: span 2">
					<span class="cz-muted" style="font-size: 0.78rem">
						<strong>{{ t('organizer.settings.audio.whisper.noDiarizationTitle') }}</strong>
						{{ t('organizer.settings.audio.whisper.noDiarization') }}
					</span>
				</div>
			</div>
		</SettingsCard>

		<VoskCards v-else-if="selected === 'vosk'" />

		<SettingsCard
			:icon="mdiSpeedometer"
			:title="t('organizer.settings.audio.limits.title')"
			:lead="t('organizer.settings.audio.limits.lead')"
			test-id="card-limits"
			v-bind="cardProps('limits')"
			@save="save('limits')">
			<div class="cz-fieldgrid">
				<div class="cz-field" style="grid-column: span 2">
					<div class="cz-modelhead">
						<span>{{ t('organizer.settings.audio.maxLive') }}</span>
						<span>{{ t('organizer.settings.audio.maxFinal') }}</span>
					</div>
					<div class="cz-modelrow">
						<input v-model.number="form.concurrency[selected].live" type="number" min="1" max="100" :aria-label="t('organizer.settings.audio.maxLive')" />
						<input v-model.number="form.concurrency[selected].batch" type="number" min="1" max="100" :aria-label="t('organizer.settings.audio.maxFinal')" />
					</div>
					<div class="cz-modelhead cz-modelhead--hint">
						<span>{{ t('organizer.settings.audio.maxLiveHint') }}</span>
						<span>{{ t('organizer.settings.audio.maxFinalHint') }}</span>
					</div>
				</div>
			</div>
		</SettingsCard>
	</div>
</template>
