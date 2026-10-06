<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import {
	mdiAccountVoice,
	mdiBrain,
	mdiCheck,
	mdiClose,
	mdiCogOutline,
	mdiDeleteClockOutline,
	mdiShieldAccountOutline,
	mdiImageOutline,
	mdiMicrophoneOutline,
} from '@mdi/js'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api, BASE } from '../api'
import { describeError } from '../errors'
import type { ProvidersSummary, SttProvider } from '../types'
import CzButton from './ui/CzButton.vue'
import CzSkeleton from './ui/CzSkeleton.vue'
import SvgIcon from './ui/SvgIcon.vue'
import { toast } from './ui/toast'

const { t } = useI18n()

const summary = ref<ProvidersSummary | null>(null)
const error = ref('')
const busy = ref(false)

const sttProvider = ref<SttProvider>('mistral')
const liveEnabled = ref(true)
const batchEnabled = ref(true)
const mistralKey = ref('')
const mistralLiveModel = ref('')
const mistralBatchModel = ref('')
const deepgramKey = ref('')
const deepgramLiveModel = ref('')
const deepgramBatchModel = ref('')
const deepgramLiveUrl = ref('')
const whisperKey = ref('')
const whisperBaseUrl = ref('')
const whisperBatchModel = ref('')
const whisperLiveModel = ref('')
const voskUrl = ref('')
const voskBatchModel = ref('')
// per-provider caps on concurrent transcription work — live caption sessions
// and final (batch) transcriptions as independent pools, server-wide.
// Uncapped, a plenary room of phones can saturate a self-hosted Vosk server
// or a provider's rate limit — then EVERY phone's captions fail at once.
const concurrency = ref<Record<SttProvider, { live: number; batch: number }>>({
	deepgram: { live: 10, batch: 5 },
	mistral: { live: 15, batch: 5 },
	vosk: { live: 5, batch: 2 },
	whisper: { live: 2, batch: 1 },
})

function clampCap(value: number): number {
	return Math.min(100, Math.max(1, Number(value) || 1))
}

// the languages an assembly can be run in (AssemblyWizard.vue). Vosk needs its
// own model for each, so every one gets a row whether or not it is configured.
// Labels are endonyms — each language names itself — so they are not translated.
const ASSEMBLY_LANGUAGES: Array<{ code: string; label: string }> = [
	{ code: 'en', label: 'English' },
	{ code: 'it', label: 'Italiano' },
	{ code: 'de', label: 'Deutsch' },
	{ code: 'fr', label: 'Français' },
	{ code: 'es', label: 'Español' },
]
const voskModels = ref<Record<string, { live: string; final: string }>>(
	Object.fromEntries(ASSEMBLY_LANGUAGES.map((l) => [l.code, { live: '', final: '' }])),
)

const STT_PROVIDERS: readonly SttProvider[] = ['mistral', 'deepgram', 'whisper', 'vosk']

// example values shown as placeholders, not prose — never translated, so they
// are plain constants rather than catalogue keys
const DEEPGRAM_ENDPOINT_EXAMPLE = 'wss://api.deepgram.com/v1/listen'
const WHISPER_BASE_URL_EXAMPLE = 'https://api.openai.com/v1'
const VOSK_URL_EXAMPLE = 'ws://localhost:2700'
const VOSK_MODEL_EXAMPLE = 'vosk-model-small-it-0.22'
const VOSK_COMMAND_EXAMPLE = 'scripts/vosk-model.sh <name>'
const ANALYSIS_BASE_URL_EXAMPLE = 'https://api.mistral.ai/v1'
const ORG_ADDRESS_EXAMPLE = 'Piazza Maggiore 6, 40124 Bologna'
const ORG_CONTACT_EMAIL_EXAMPLE = 'privacy@example.org'
const ORG_AUTHORITY_EXAMPLE = 'Garante per la protezione dei dati personali'
const ORG_NAME_EXAMPLE = 'Democracy Innovators'

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
const analysisBaseUrl = ref('')
const analysisModel = ref('')
const analysisKey = ref('')
const analysisEnabled = ref(true)
const analysisExtra = ref('')
// the AI facilitator: its own level and model, falling back to the analysis model
type FacilitatorLevel = 'off' | 'light' | 'normal' | 'active'
const FACILITATOR_LEVELS: readonly FacilitatorLevel[] = ['off', 'light', 'normal', 'active']
const facLevel = ref<FacilitatorLevel>('off')
const facBaseUrl = ref('')
const facModel = ref('')
const facKey = ref('')
const facInterval = ref(4)
const facDominance = ref(60)
const facSilence = ref(90)
const facAdvanced = ref(false)
const orgName = ref('')
const retentionDays = ref(0)
// the consent notice: who is responsible for the data, and how to reach them
const consentController = ref('')
const consentContact = ref('')
const orgAddress = ref('')
const orgDpo = ref('')
const orgHosting = ref('')
const orgAuthority = ref('')
const showPrompts = ref(false)
const logoSet = ref(false)
const logoVersion = ref(0)
const testResults = ref<Record<string, { ok: boolean; message: string }>>({})

type Tab = 'audio' | 'ai' | 'general'
const tab = ref<Tab>('audio')
const tabs = computed<Array<{ id: Tab; label: string; icon: string }>>(() => [
	{ id: 'audio', label: t('organizer.settings.tabs.audio'), icon: mdiMicrophoneOutline },
	{ id: 'ai', label: t('organizer.settings.tabs.ai'), icon: mdiBrain },
	{ id: 'general', label: t('organizer.settings.tabs.general'), icon: mdiCogOutline },
])

function logoUrl(): string {
	return `${BASE}/api/v1/admin/logo?v=${logoVersion.value}`
}

async function uploadLogo(event: Event): Promise<void> {
	const input = event.target as HTMLInputElement
	const file = input.files?.[0]
	input.value = ''
	if (!file) return
	if (file.size > 1_000_000) {
		error.value = t('organizer.settings.branding.tooLarge')
		return
	}
	busy.value = true
	error.value = ''
	try {
		const buffer = await file.arrayBuffer()
		let binary = ''
		for (const byte of new Uint8Array(buffer)) binary += String.fromCharCode(byte)
		await api.uploadLogo(btoa(binary))
		logoSet.value = true
		logoVersion.value += 1
		toast(t('organizer.settings.branding.logoSaved'))
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err)
	} finally {
		busy.value = false
	}
}

async function removeLogo(): Promise<void> {
	busy.value = true
	try {
		await api.deleteLogo()
		logoSet.value = false
		toast(t('organizer.settings.branding.logoRemoved'))
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err)
	} finally {
		busy.value = false
	}
}

async function reload(): Promise<void> {
	summary.value = await api.getProviders()
	sttProvider.value = summary.value.stt.provider
	liveEnabled.value = summary.value.stt.live_enabled
	batchEnabled.value = summary.value.stt.batch_enabled
	mistralLiveModel.value = summary.value.stt.mistral_live_model
	mistralBatchModel.value = summary.value.stt.mistral_batch_model
	deepgramLiveModel.value = summary.value.stt.deepgram_live_model
	deepgramBatchModel.value = summary.value.stt.deepgram_batch_model
	deepgramLiveUrl.value = summary.value.stt.deepgram_live_url
	whisperBaseUrl.value = summary.value.stt.whisper_base_url
	whisperBatchModel.value = summary.value.stt.whisper_batch_model
	whisperLiveModel.value = summary.value.stt.whisper_live_model ?? ''
	voskUrl.value = summary.value.stt.vosk_url
	voskBatchModel.value = summary.value.stt.vosk_batch_model
	concurrency.value = {
		deepgram: {
			live: summary.value.stt.stt_concurrency_deepgram_live ?? 10,
			batch: summary.value.stt.stt_concurrency_deepgram_batch ?? 5,
		},
		mistral: {
			live: summary.value.stt.stt_concurrency_mistral_live ?? 15,
			batch: summary.value.stt.stt_concurrency_mistral_batch ?? 5,
		},
		vosk: {
			live: summary.value.stt.stt_concurrency_vosk_live ?? 5,
			batch: summary.value.stt.stt_concurrency_vosk_batch ?? 2,
		},
		whisper: {
			live: summary.value.stt.stt_concurrency_whisper_live ?? 2,
			batch: summary.value.stt.stt_concurrency_whisper_batch ?? 1,
		},
	}
	const stored = summary.value.stt.vosk_language_models ?? {}
	voskModels.value = Object.fromEntries(
		ASSEMBLY_LANGUAGES.map(({ code }) => [
			code,
			{ live: stored[code]?.live ?? '', final: stored[code]?.final ?? '' },
		]),
	)
	analysisBaseUrl.value = summary.value.analysis.base_url
	analysisModel.value = summary.value.analysis.model
	analysisEnabled.value = summary.value.analysis.enabled
	analysisExtra.value = summary.value.analysis.extra_instructions
	if (summary.value.facilitator) {
		facLevel.value = summary.value.facilitator.level
		facBaseUrl.value = summary.value.facilitator.base_url
		facModel.value = summary.value.facilitator.model
		facInterval.value = summary.value.facilitator.interval_minutes
		facDominance.value = summary.value.facilitator.dominance_percent
		facSilence.value = summary.value.facilitator.silence_seconds
	}
	orgName.value = summary.value.organization_name
	retentionDays.value = summary.value.audio_retention_days ?? 0
	consentController.value = summary.value.consent_controller ?? ''
	consentContact.value = summary.value.consent_contact ?? ''
	orgAddress.value = summary.value.org_address ?? ''
	orgDpo.value = summary.value.org_dpo ?? ''
	orgHosting.value = summary.value.org_hosting ?? ''
	orgAuthority.value = summary.value.org_authority ?? ''
	logoSet.value = summary.value.logo_set
	// the baseline every later edit is compared against
	saved.value = snapshot()
}

onMounted(async () => {
	try {
		await reload()
	} catch (err) {
		error.value = describeError(err).message
	}
})

/** Warn before a reload or a close throws away unsaved settings.
 *
 * Not a substitute for noticing the button says "Save settings" — it is the
 * backstop for the tab that is currently hidden. */
function warnIfDirty(event: BeforeUnloadEvent): void {
	if (!dirty.value) return
	event.preventDefault()
	event.returnValue = ''
}

onMounted(() => window.addEventListener('beforeunload', warnIfDirty))
onBeforeUnmount(() => window.removeEventListener('beforeunload', warnIfDirty))

/** What the form held when it was last loaded or saved.
 *
 * One "Save settings" button persists every field on every tab, and the tabs
 * are v-show — so an admin who came to change one Vosk URL also committed
 * whatever was sitting on the AI tab, with nothing on screen saying so.
 */
const saved = ref('')

function snapshot(): string {
	return JSON.stringify(currentPayload())
}

const dirty = computed(() => saved.value !== '' && saved.value !== snapshot())

function currentPayload(): Record<string, unknown> {
	return {
			stt_provider: sttProvider.value,
			stt_live_enabled: liveEnabled.value,
			stt_batch_enabled: batchEnabled.value,
			mistral_live_model: mistralLiveModel.value.trim(),
			mistral_batch_model: mistralBatchModel.value.trim(),
			deepgram_live_model: deepgramLiveModel.value.trim(),
			deepgram_batch_model: deepgramBatchModel.value.trim(),
			deepgram_live_url: deepgramLiveUrl.value.trim(),
			whisper_base_url: whisperBaseUrl.value.trim(),
			whisper_batch_model: whisperBatchModel.value.trim(),
			whisper_live_model: whisperLiveModel.value.trim(),
			vosk_url: voskUrl.value.trim(),
			vosk_batch_model: voskBatchModel.value.trim(),
			// clamp locally so a cleared field round-trips as the minimum
			// rather than a 422 from the server
			stt_concurrency_deepgram_live: clampCap(concurrency.value.deepgram.live),
			stt_concurrency_deepgram_batch: clampCap(concurrency.value.deepgram.batch),
			stt_concurrency_mistral_live: clampCap(concurrency.value.mistral.live),
			stt_concurrency_mistral_batch: clampCap(concurrency.value.mistral.batch),
			stt_concurrency_vosk_live: clampCap(concurrency.value.vosk.live),
			stt_concurrency_vosk_batch: clampCap(concurrency.value.vosk.batch),
			stt_concurrency_whisper_live: clampCap(concurrency.value.whisper.live),
			stt_concurrency_whisper_batch: clampCap(concurrency.value.whisper.batch),
			vosk_language_models: JSON.stringify(
				Object.fromEntries(
					Object.entries(voskModels.value)
						.map(([code, row]) => [
							code,
							{ live: row.live.trim(), final: row.final.trim() },
						])
						// a language with neither model set is simply not configured
						.filter(([, row]) => (row as { live: string; final: string }).live
							|| (row as { live: string; final: string }).final),
				),
			),
			analysis_base_url: analysisBaseUrl.value.trim(),
			analysis_model: analysisModel.value.trim(),
			analysis_enabled: analysisEnabled.value,
			analysis_extra_instructions: analysisExtra.value.trim(),
			facilitator_level: facLevel.value,
			facilitator_base_url: facBaseUrl.value.trim(),
			facilitator_model: facModel.value.trim(),
			facilitator_interval_minutes: Number(facInterval.value) || 4,
			facilitator_dominance_percent: Number(facDominance.value) || 60,
			facilitator_silence_seconds: Number(facSilence.value) || 90,
			organization_name: orgName.value.trim(),
			audio_retention_days: Number(retentionDays.value) || 0,
			consent_controller: consentController.value.trim(),
			consent_contact: consentContact.value.trim(),
			org_address: orgAddress.value.trim(),
			org_dpo: orgDpo.value.trim(),
			org_hosting: orgHosting.value.trim(),
			org_authority: orgAuthority.value.trim(),
	}
}

async function save(): Promise<void> {
	busy.value = true
	error.value = ''
	try {
		// only what changed since the last load or save: every field posted
		// is a write through Nextcloud, and one Vosk URL used to cost thirty
		const current = currentPayload()
		const base: Record<string, unknown> = saved.value ? JSON.parse(saved.value) : {}
		const payload: Record<string, unknown> = {}
		for (const [key, value] of Object.entries(current)) {
			if (JSON.stringify(value) !== JSON.stringify(base[key])) payload[key] = value
		}
		// secrets are only sent when actually retyped, so they are deliberately
		// outside currentPayload() and therefore outside the dirty comparison
		if (mistralKey.value) payload.mistral_api_key = mistralKey.value
		if (deepgramKey.value) payload.deepgram_api_key = deepgramKey.value
		if (whisperKey.value) payload.whisper_api_key = whisperKey.value
		if (analysisKey.value) payload.analysis_api_key = analysisKey.value
		if (facKey.value) payload.facilitator_api_key = facKey.value
		summary.value = await api.updateProviders(payload)
		mistralKey.value = ''
		deepgramKey.value = ''
		whisperKey.value = ''
		analysisKey.value = ''
		facKey.value = ''
		saved.value = snapshot()
		toast(t('organizer.settings.page.settingsSaved'))
	} catch (err) {
		error.value = describeError(err).message
	} finally {
		busy.value = false
	}
}

async function test(target: SttProvider | 'analysis' | 'facilitator'): Promise<void> {
	busy.value = true
	try {
		const typedKeys: Record<string, string> = {
			mistral: mistralKey.value,
			deepgram: deepgramKey.value,
			whisper: whisperKey.value,
			analysis: analysisKey.value,
			facilitator: facKey.value,
		}
		const typed = typedKeys[target] ?? ''
		const baseUrls: Record<string, string> = {
			analysis: analysisBaseUrl.value.trim(),
			facilitator: facBaseUrl.value.trim(),
			whisper: whisperBaseUrl.value.trim(),
			vosk: voskUrl.value.trim(),
		}
		const baseUrl = baseUrls[target]
		// the analysis test makes one real completion: with the model in the
		// form, not the saved one, or a typed replacement can never be tested
		const model =
			target === 'analysis'
				? analysisModel.value.trim() || undefined
				: target === 'facilitator'
					? facModel.value.trim() || undefined
					: undefined
		testResults.value = {
			...testResults.value,
			[target]: await api.testProvider(target, typed.trim() || undefined, baseUrl, model),
		}
	} catch (err) {
		testResults.value = {
			...testResults.value,
			[target]: { ok: false, message: err instanceof Error ? err.message : String(err) },
		}
	} finally {
		busy.value = false
	}
}

function keyPlaceholder(configured: boolean, hint: string): string {
	return configured
		? t('organizer.settings.audio.keyConfigured', { hint })
		: t('organizer.settings.audio.pasteKey')
}
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
			<CzButton variant="primary" :disabled="busy || !summary" @click="save">
				{{ busy ? t('organizer.settings.page.saving') : dirty ? t('organizer.settings.page.save') : t('organizer.settings.page.saved') }}
			</CzButton>
		</div>

		<!-- The tabs are v-show and one button commits all of them, so an admin
		     who came to change a single Vosk URL also saves whatever is sitting
		     on a tab they are not looking at. Saying so is cheaper than
		     splitting the form, and it is the surprise that mattered. -->
		<p v-if="dirty" class="cz-muted cz-text-sm" style="margin: 0 0 12px">
			{{ t('organizer.settings.page.unsaved') }}
		</p>

		<div v-if="error" class="cz-error">{{ error }}</div>
		<CzSkeleton v-if="!summary && !error" :rows="3" :height="120" />

		<template v-if="summary">
			<div class="cz-tabs" role="tablist">
				<button
					v-for="item in tabs"
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

			<div v-show="tab === 'audio'" class="cz-card">
				<div class="cz-row" style="margin-bottom: 14px">
					<SvgIcon :path="mdiMicrophoneOutline" :size="22" style="color: var(--cz-primary)" />
					<h3>{{ t('organizer.settings.audio.title') }}</h3>
				</div>

				<div class="cz-row" style="margin-bottom: 16px">
					<label
						v-for="provider in STT_PROVIDERS"
						:key="provider"
						class="cz-radiocard"
						:class="{ 'cz-radiocard--checked': sttProvider === provider }">
						<input v-model="sttProvider" type="radio" :value="provider" />
						<SvgIcon v-if="sttProvider === provider" :path="mdiCheck" :size="16" />
						{{ providerLabel[provider] }}
					</label>
				</div>

				<p style="font-size: 0.875rem; margin: -4px 0 10px">
					{{ t('organizer.settings.audio.selectedService') }} <strong style="color: var(--cz-primary)">{{ providerLabel[sttProvider] }}</strong>
					{{ t('organizer.settings.audio.selectedHint') }}
				</p>
				<p class="cz-muted" style="font-size: 0.8125rem; margin: -6px 0 14px">
					{{ captionNote[sttProvider] }}
					{{ t('organizer.settings.audio.provisional') }}
				</p>

				<div v-if="sttProvider === 'mistral'" class="cz-fieldgrid">
					<div class="cz-field">
						<label>{{ t('organizer.settings.audio.mistral.key') }}</label>
						<div class="cz-row" style="flex-wrap: nowrap">
							<input
								v-model="mistralKey"
								type="password"
								autocomplete="off"
								style="flex: 1"
								:placeholder="keyPlaceholder(summary.stt.mistral_configured, summary.stt.mistral_key_hint)" />
							<CzButton small :disabled="busy" @click="test('mistral')">{{ t('organizer.settings.audio.test') }}</CzButton>
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
							<input v-model="mistralLiveModel" type="text" placeholder="voxtral-mini-transcribe-realtime-2602" :aria-label="t('organizer.settings.audio.liveModelAria')" />
							<input v-model="mistralBatchModel" type="text" placeholder="voxtral-mini-latest" :aria-label="t('organizer.settings.audio.finalModelAria')" />
						</div>
						<div class="cz-modelhead cz-modelhead--hint">
							<span>{{ t('organizer.settings.audio.mistral.liveHint') }}</span>
							<span>{{ t('organizer.settings.audio.finalHint') }}</span>
						</div>
					</div>
					<div class="cz-field" style="grid-column: span 2">
						<div class="cz-modelhead">
							<span>{{ t('organizer.settings.audio.maxLive') }}</span>
							<span>{{ t('organizer.settings.audio.maxFinal') }}</span>
						</div>
						<div class="cz-modelrow">
							<input v-model.number="concurrency.mistral.live" type="number" min="1" max="100" :aria-label="t('organizer.settings.audio.maxLive')" />
							<input v-model.number="concurrency.mistral.batch" type="number" min="1" max="100" :aria-label="t('organizer.settings.audio.maxFinal')" />
						</div>
						<div class="cz-modelhead cz-modelhead--hint">
							<span>{{ t('organizer.settings.audio.maxLiveHint') }}</span>
							<span>{{ t('organizer.settings.audio.maxFinalHint') }}</span>
						</div>
					</div>
				</div>
				<div v-else-if="sttProvider === 'deepgram'" class="cz-fieldgrid">
					<div class="cz-field">
						<label>{{ t('organizer.settings.audio.deepgram.key') }}</label>
						<div class="cz-row" style="flex-wrap: nowrap">
							<input
								v-model="deepgramKey"
								type="password"
								autocomplete="off"
								style="flex: 1"
								:placeholder="keyPlaceholder(summary.stt.deepgram_configured, summary.stt.deepgram_key_hint)" />
							<CzButton small :disabled="busy" @click="test('deepgram')">{{ t('organizer.settings.audio.test') }}</CzButton>
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
							<input v-model="deepgramLiveModel" type="text" placeholder="nova-3" :aria-label="t('organizer.settings.audio.liveModelAria')" />
							<input v-model="deepgramBatchModel" type="text" placeholder="nova-3" :aria-label="t('organizer.settings.audio.finalModelAria')" />
						</div>
						<div class="cz-modelhead cz-modelhead--hint">
							<span>{{ t('organizer.settings.audio.deepgram.liveHint') }}</span>
							<span>{{ t('organizer.settings.audio.finalHint') }}</span>
						</div>
					</div>
					<div class="cz-field" style="grid-column: span 2">
						<div class="cz-modelhead">
							<span>{{ t('organizer.settings.audio.maxLive') }}</span>
							<span>{{ t('organizer.settings.audio.maxFinal') }}</span>
						</div>
						<div class="cz-modelrow">
							<input v-model.number="concurrency.deepgram.live" type="number" min="1" max="100" :aria-label="t('organizer.settings.audio.maxLive')" />
							<input v-model.number="concurrency.deepgram.batch" type="number" min="1" max="100" :aria-label="t('organizer.settings.audio.maxFinal')" />
						</div>
						<div class="cz-modelhead cz-modelhead--hint">
							<span>{{ t('organizer.settings.audio.maxLiveHint') }}</span>
							<span>{{ t('organizer.settings.audio.maxFinalHint') }}</span>
						</div>
					</div>
					<div class="cz-field" style="grid-column: span 2">
						<label>{{ t('organizer.settings.audio.deepgram.endpoint') }}</label>
						<input v-model="deepgramLiveUrl" type="text" :placeholder="DEEPGRAM_ENDPOINT_EXAMPLE" />
						<span class="cz-muted" style="font-size: 0.78rem">
							{{ t('organizer.settings.audio.deepgram.endpointHint') }}
						</span>
					</div>
				</div>

				<div v-else-if="sttProvider === 'whisper'" class="cz-fieldgrid">
					<div class="cz-field" style="grid-column: span 2">
						<label>{{ t('organizer.settings.audio.whisper.baseUrl') }}</label>
						<input v-model="whisperBaseUrl" type="text" :placeholder="WHISPER_BASE_URL_EXAMPLE" />
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
							<input v-model="whisperLiveModel" type="text" :placeholder="t('organizer.settings.audio.whisper.sameAsFinal')" :aria-label="t('organizer.settings.audio.liveModelAria')" />
							<input v-model="whisperBatchModel" type="text" placeholder="whisper-1" :aria-label="t('organizer.settings.audio.finalModelAria')" />
						</div>
						<div class="cz-modelhead cz-modelhead--hint">
							<span>{{ t('organizer.settings.audio.whisper.liveHint') }}</span>
							<span>{{ t('organizer.settings.audio.whisper.finalHint') }}</span>
						</div>
					</div>
					<div class="cz-field" style="grid-column: span 2">
						<div class="cz-modelhead">
							<span>{{ t('organizer.settings.audio.maxLive') }}</span>
							<span>{{ t('organizer.settings.audio.maxFinal') }}</span>
						</div>
						<div class="cz-modelrow">
							<input v-model.number="concurrency.whisper.live" type="number" min="1" max="100" :aria-label="t('organizer.settings.audio.maxLive')" />
							<input v-model.number="concurrency.whisper.batch" type="number" min="1" max="100" :aria-label="t('organizer.settings.audio.maxFinal')" />
						</div>
						<div class="cz-modelhead cz-modelhead--hint">
							<span>{{ t('organizer.settings.audio.maxLiveHint') }}</span>
							<span>{{ t('organizer.settings.audio.maxFinalHint') }}</span>
						</div>
					</div>
					<div class="cz-field">
						<label>{{ t('organizer.settings.audio.whisper.key') }}</label>
						<div class="cz-row" style="flex-wrap: nowrap">
							<input
								v-model="whisperKey"
								type="password"
								autocomplete="off"
								style="flex: 1"
								:placeholder="keyPlaceholder(summary.stt.whisper_configured, summary.stt.whisper_key_hint)" />
							<CzButton small :disabled="busy" @click="test('whisper')">{{ t('organizer.settings.audio.test') }}</CzButton>
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

				<div v-else class="cz-fieldgrid">
					<div class="cz-field" style="grid-column: span 2">
						<label>{{ t('organizer.settings.audio.vosk.url') }}</label>
						<div class="cz-row" style="flex-wrap: nowrap">
							<input v-model="voskUrl" type="text" style="flex: 1" :placeholder="VOSK_URL_EXAMPLE" />
							<CzButton small :disabled="busy" @click="test('vosk')">{{ t('organizer.settings.audio.test') }}</CzButton>
						</div>
						<span v-if="testResults.vosk" class="cz-pill" :class="testResults.vosk.ok ? 'cz-pill--green' : 'cz-pill--orange'" style="text-transform: none; align-self: flex-start">
							<SvgIcon :path="testResults.vosk.ok ? mdiCheck : mdiClose" :size="14" />
							{{ testResults.vosk.message }}
						</span>
						<span class="cz-muted" style="font-size: 0.78rem">
							{{ t('organizer.settings.audio.vosk.urlHint') }}
						</span>
					</div>
					<div class="cz-field" style="grid-column: span 2">
						<label>{{ t('organizer.settings.audio.vosk.perLanguage') }}</label>
						<i18n-t
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
							<input
								v-model="voskModels[lang.code].live"
								type="text"
								:placeholder="t('organizer.settings.audio.vosk.notConfigured')"
								:aria-label="t('organizer.settings.audio.vosk.liveModelFor', { language: lang.label })" />
							<input
								v-model="voskModels[lang.code].final"
								type="text"
								:placeholder="t('organizer.settings.audio.vosk.sameAsLive')"
								:aria-label="t('organizer.settings.audio.vosk.finalModelFor', { language: lang.label })" />
						</div>
						<span class="cz-muted" style="font-size: 0.78rem; margin-top: 6px">
							{{ t('organizer.settings.audio.vosk.blankHint') }}
						</span>
					</div>
					<div class="cz-field" style="grid-column: span 2">
						<div class="cz-modelhead">
							<span>{{ t('organizer.settings.audio.maxLive') }}</span>
							<span>{{ t('organizer.settings.audio.maxFinal') }}</span>
						</div>
						<div class="cz-modelrow">
							<input v-model.number="concurrency.vosk.live" type="number" min="1" max="100" :aria-label="t('organizer.settings.audio.maxLive')" />
							<input v-model.number="concurrency.vosk.batch" type="number" min="1" max="100" :aria-label="t('organizer.settings.audio.maxFinal')" />
						</div>
						<div class="cz-modelhead cz-modelhead--hint">
							<span>{{ t('organizer.settings.audio.maxLiveHint') }}</span>
							<span>{{ t('organizer.settings.audio.maxFinalHint') }}</span>
						</div>
					</div>
					<div class="cz-field">
						<label>{{ t('organizer.settings.audio.vosk.label') }}</label>
						<input v-model="voskBatchModel" type="text" :placeholder="VOSK_MODEL_EXAMPLE" />
						<span class="cz-muted" style="font-size: 0.78rem">
							{{ t('organizer.settings.audio.vosk.labelHint') }}
						</span>
					</div>
					<div class="cz-field" style="grid-column: span 2">
						<span class="cz-muted" style="font-size: 0.78rem">
							<strong>{{ t('organizer.settings.audio.vosk.plainTitle') }}</strong>
							{{ t('organizer.settings.audio.vosk.plain') }}
						</span>
					</div>
				</div>

				<div class="cz-row" style="gap: 24px; margin-top: 4px">
					<label style="display: flex; align-items: center; gap: 8px; cursor: pointer">
						<input v-model="liveEnabled" type="checkbox" /> {{ t('organizer.settings.audio.liveHead') }}
					</label>
					<label style="display: flex; align-items: center; gap: 8px; cursor: pointer">
						<input v-model="batchEnabled" type="checkbox" /> {{ t('organizer.settings.audio.finalHead') }}
					</label>
				</div>
				<span class="cz-muted" style="font-size: 0.78rem; display: block; margin-top: 8px">
					<template v-if="liveEnabled && batchEnabled">
						{{ t('organizer.settings.audio.modes.both') }}
					</template>
					<template v-else-if="batchEnabled">
						{{ t('organizer.settings.audio.modes.finalOnly') }}
					</template>
					<template v-else-if="liveEnabled">
						<strong>{{ t('organizer.settings.audio.modes.liveOnlyTitle') }}</strong>
						{{ t('organizer.settings.audio.modes.liveOnly') }}
					</template>
					<template v-else>
						<strong style="color: var(--cz-danger)">{{ t('organizer.settings.audio.modes.noneTitle') }}</strong>
						{{ t('organizer.settings.audio.modes.none') }}
					</template>
				</span>
			</div>

			<div v-show="tab === 'ai'" class="cz-card">
				<div class="cz-row" style="margin-bottom: 4px">
					<SvgIcon :path="mdiBrain" :size="22" style="color: var(--cz-primary)" />
					<h3>{{ t('organizer.settings.ai.title') }}</h3>
				</div>
				<p class="cz-muted" style="font-size: 0.845rem; margin-bottom: 14px">
					{{ t('organizer.settings.ai.lead') }}
				</p>
				<label style="display: flex; align-items: center; gap: 8px; cursor: pointer; margin-bottom: 14px">
					<input v-model="analysisEnabled" type="checkbox" />
					{{ t('organizer.settings.ai.auto') }}
				</label>
				<div class="cz-fieldgrid">
					<div class="cz-field" style="grid-column: span 2">
						<label>{{ t('organizer.settings.ai.baseUrl') }}</label>
						<input v-model="analysisBaseUrl" type="text" :placeholder="ANALYSIS_BASE_URL_EXAMPLE" />
					</div>
					<div class="cz-field">
						<label>{{ t('organizer.settings.ai.model') }}</label>
						<input v-model="analysisModel" type="text" placeholder="mistral-large-latest" />
					</div>
					<div class="cz-field">
						<label>{{ t('organizer.settings.ai.key') }}</label>
						<div class="cz-row" style="flex-wrap: nowrap">
							<input
								v-model="analysisKey"
								type="password"
								autocomplete="off"
								style="flex: 1"
								:placeholder="keyPlaceholder(summary.analysis.configured, summary.analysis.key_hint)" />
							<CzButton small :disabled="busy" @click="test('analysis')">{{ t('organizer.settings.audio.test') }}</CzButton>
						</div>
						<span v-if="testResults.analysis" class="cz-pill" :class="testResults.analysis.ok ? 'cz-pill--green' : 'cz-pill--orange'" style="text-transform: none; align-self: flex-start">
							<SvgIcon :path="testResults.analysis.ok ? mdiCheck : mdiClose" :size="14" />
							{{ testResults.analysis.message }}
						</span>
					</div>
				</div>

				<div class="cz-field" style="margin-top: 12px">
					<label>{{ t('organizer.settings.ai.extra') }}</label>
					<textarea
						v-model="analysisExtra"
						rows="4"
						:placeholder="t('organizer.settings.ai.extraPlaceholder')"></textarea>
					<span class="cz-muted" style="font-size: 0.78rem">
						{{ t('organizer.settings.ai.extraHint') }}
					</span>
				</div>

				<!-- the AI facilitator: opt-in, its own model, conservative by design -->
				<div class="cz-row" style="margin: 22px 0 4px">
					<SvgIcon :path="mdiAccountVoice" :size="22" style="color: var(--cz-primary)" />
					<h3>{{ t('organizer.settings.facilitator.title') }}</h3>
				</div>
				<p class="cz-muted" style="font-size: 0.845rem; margin-bottom: 10px">
					{{ t('organizer.settings.facilitator.lead') }}
				</p>
				<div class="cz-field" data-test="facilitator-level">
					<label>{{ t('organizer.settings.facilitator.level') }}</label>
					<div class="cz-row" style="gap: 14px; flex-wrap: wrap">
						<label v-for="level in FACILITATOR_LEVELS" :key="level" style="display: flex; align-items: center; gap: 6px; cursor: pointer">
							<input v-model="facLevel" type="radio" :value="level" />
							{{ t(`organizer.settings.facilitator.levels.${level}`) }}
						</label>
					</div>
				</div>
				<div class="cz-fieldgrid" style="margin-top: 10px">
					<div class="cz-field" style="grid-column: span 2">
						<label>{{ t('organizer.settings.facilitator.baseUrl') }}</label>
						<input v-model="facBaseUrl" type="text" :placeholder="analysisBaseUrl || 'https://api.mistral.ai/v1'" />
					</div>
					<div class="cz-field">
						<label>{{ t('organizer.settings.facilitator.model') }}</label>
						<input v-model="facModel" type="text" :placeholder="analysisModel || 'mistral-small-latest'" />
					</div>
					<div class="cz-field">
						<label>{{ t('organizer.settings.facilitator.key') }}</label>
						<div class="cz-row" style="flex-wrap: nowrap">
							<input
								v-model="facKey"
								type="password"
								autocomplete="off"
								style="flex: 1"
								:placeholder="keyPlaceholder(summary.facilitator?.own_key ?? false, summary.facilitator?.key_hint ?? '')" />
							<CzButton small :disabled="busy" data-test="test-facilitator" @click="test('facilitator')">{{ t('organizer.settings.audio.test') }}</CzButton>
						</div>
						<span v-if="testResults.facilitator" class="cz-pill" :class="testResults.facilitator.ok ? 'cz-pill--green' : 'cz-pill--orange'" style="text-transform: none; align-self: flex-start">
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
						<input v-model.number="facInterval" type="number" min="1" max="60" />
					</div>
					<div class="cz-field">
						<label>{{ t('organizer.settings.facilitator.dominance') }}</label>
						<input v-model.number="facDominance" type="number" min="40" max="95" />
					</div>
					<div class="cz-field">
						<label>{{ t('organizer.settings.facilitator.silence') }}</label>
						<input v-model.number="facSilence" type="number" min="20" max="600" />
					</div>
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
			</div>

			<div v-show="tab === 'general'" class="cz-card">
				<div class="cz-row" style="margin-bottom: 4px">
					<SvgIcon :path="mdiDeleteClockOutline" :size="22" style="color: var(--cz-primary)" />
					<h3>{{ t('organizer.settings.retention.title') }}</h3>
				</div>
				<i18n-t
					keypath="organizer.settings.retention.lead"
					tag="p"
					class="cz-muted"
					style="font-size: 0.845rem; margin-bottom: 14px">
					<template #closed><strong>{{ t('organizer.settings.retention.closed') }}</strong></template>
				</i18n-t>
				<div class="cz-field" style="max-width: 260px">
					<label>{{ t('organizer.settings.retention.days') }}</label>
					<input v-model.number="retentionDays" type="number" min="0" max="3650" />
					<p class="cz-muted" style="font-size: 0.78rem; margin-top: 6px">
						{{
							Number(retentionDays) > 0
								? t('organizer.settings.retention.deletedAfter', { days: retentionDays })
								: t('organizer.settings.retention.keptForever')
						}}
					</p>
				</div>
			</div>

			<div v-show="tab === 'general'" class="cz-card">
				<div class="cz-row" style="margin-bottom: 4px">
					<SvgIcon :path="mdiShieldAccountOutline" :size="22" style="color: var(--cz-primary)" />
					<h3>{{ t('organizer.settings.org.title') }}</h3>
				</div>
				<p class="cz-muted" style="font-size: 0.845rem; margin-bottom: 14px">
					{{ t('organizer.settings.org.lead') }}
				</p>
				<div class="cz-field" style="max-width: 420px">
					<label>{{ t('organizer.settings.org.controller') }}</label>
					<input v-model="consentController" type="text" :placeholder="orgName || t('organizer.settings.org.controllerPlaceholder')" />
					<p class="cz-muted" style="font-size: 0.78rem; margin-top: 6px">
						{{ t('organizer.settings.org.controllerHint') }}
					</p>
				</div>
				<div class="cz-field" style="max-width: 420px">
					<label>{{ t('organizer.settings.org.address') }}</label>
					<input v-model="orgAddress" type="text" :placeholder="ORG_ADDRESS_EXAMPLE" />
				</div>
				<div class="cz-field" style="max-width: 420px">
					<label>{{ t('organizer.settings.org.contact') }}</label>
					<input v-model="consentContact" type="text" :placeholder="ORG_CONTACT_EMAIL_EXAMPLE" />
				</div>
				<div class="cz-field" style="max-width: 420px">
					<label>{{ t('organizer.settings.org.dpo') }}</label>
					<input v-model="orgDpo" type="text" :placeholder="t('organizer.settings.org.dpoPlaceholder')" />
				</div>
				<div class="cz-field" style="max-width: 420px">
					<label>{{ t('organizer.settings.org.hosting') }}</label>
					<input v-model="orgHosting" type="text" :placeholder="t('organizer.settings.org.hostingPlaceholder')" />
					<p class="cz-muted" style="font-size: 0.78rem; margin-top: 6px">
						{{ t('organizer.settings.org.hostingHint') }}
					</p>
				</div>
				<div class="cz-field" style="max-width: 420px">
					<label>{{ t('organizer.settings.org.authority') }}</label>
					<input v-model="orgAuthority" type="text" :placeholder="ORG_AUTHORITY_EXAMPLE" />
					<p class="cz-muted" style="font-size: 0.78rem; margin-top: 6px">
						{{ t('organizer.settings.org.authorityHint') }}
					</p>
				</div>
			</div>

			<div v-show="tab === 'general'" class="cz-card">
				<div class="cz-row" style="margin-bottom: 4px">
					<SvgIcon :path="mdiImageOutline" :size="22" style="color: var(--cz-primary)" />
					<h3>{{ t('organizer.settings.branding.title') }}</h3>
				</div>
				<p class="cz-muted" style="font-size: 0.845rem; margin-bottom: 14px">
					{{ t('organizer.settings.branding.lead') }}
				</p>
				<div class="cz-field" style="max-width: 420px">
					<label>{{ t('organizer.settings.branding.name') }}</label>
					<input v-model="orgName" type="text" :placeholder="ORG_NAME_EXAMPLE" />
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
					<CzButton v-if="logoSet" small variant="tertiary" :disabled="busy" @click="removeLogo">
						{{ t('organizer.settings.branding.remove') }}
					</CzButton>
				</div>
			</div>
		</template>
	</div>
</template>
