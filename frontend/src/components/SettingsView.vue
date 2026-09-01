<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import {
	mdiBrain,
	mdiCheck,
	mdiClose,
	mdiCogOutline,
	mdiDeleteClockOutline,
	mdiImageOutline,
	mdiMicrophoneOutline,
} from '@mdi/js'
import { onMounted, ref } from 'vue'
import { api, BASE } from '../api'
import type { ProvidersSummary, SttProvider } from '../types'
import CzButton from './ui/CzButton.vue'
import CzSkeleton from './ui/CzSkeleton.vue'
import SvgIcon from './ui/SvgIcon.vue'
import { toast } from './ui/toast'

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

// the languages an assembly can be run in (AssemblyWizard.vue). Vosk needs its
// own model for each, so every one gets a row whether or not it is configured.
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

// every engine produces live captions, each through its own protocol
const CAPTION_NOTE: Record<SttProvider, string> = {
	deepgram: 'Live captions stream natively and carry speaker labels.',
	mistral: 'Live captions use Voxtral Realtime; realtime output has no speaker labels.',
	whisper: 'Live captions are produced from rolling 20-second windows, so a line may be revised as more audio arrives.',
	vosk: 'Live captions stream natively from your Vosk server, without punctuation or speaker labels.',
}
const analysisBaseUrl = ref('')
const analysisModel = ref('')
const analysisKey = ref('')
const analysisEnabled = ref(true)
const analysisExtra = ref('')
const orgName = ref('')
const retentionDays = ref(0)
const showPrompts = ref(false)
const logoSet = ref(false)
const logoVersion = ref(0)
const testResults = ref<Record<string, { ok: boolean; message: string }>>({})

type Tab = 'audio' | 'ai' | 'general'
const tab = ref<Tab>('audio')
const TABS: Array<{ id: Tab; label: string; icon: string }> = [
	{ id: 'audio', label: 'Audio', icon: mdiMicrophoneOutline },
	{ id: 'ai', label: 'AI analysis', icon: mdiBrain },
	{ id: 'general', label: 'General', icon: mdiCogOutline },
]

function logoUrl(): string {
	return `${BASE}/api/v1/admin/logo?v=${logoVersion.value}`
}

async function uploadLogo(event: Event): Promise<void> {
	const input = event.target as HTMLInputElement
	const file = input.files?.[0]
	input.value = ''
	if (!file) return
	if (file.size > 1_000_000) {
		error.value = 'Logo must be 1 MB or smaller'
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
		toast('Logo saved — it will appear on PDF reports')
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
		toast('Logo removed')
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
	orgName.value = summary.value.organization_name
	retentionDays.value = summary.value.audio_retention_days ?? 0
	logoSet.value = summary.value.logo_set
}

onMounted(async () => {
	try {
		await reload()
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err)
	}
})

async function save(): Promise<void> {
	busy.value = true
	error.value = ''
	try {
		const payload: Record<string, unknown> = {
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
			organization_name: orgName.value.trim(),
			audio_retention_days: Number(retentionDays.value) || 0,
		}
		if (mistralKey.value) payload.mistral_api_key = mistralKey.value
		if (deepgramKey.value) payload.deepgram_api_key = deepgramKey.value
		if (whisperKey.value) payload.whisper_api_key = whisperKey.value
		if (analysisKey.value) payload.analysis_api_key = analysisKey.value
		summary.value = await api.updateProviders(payload)
		mistralKey.value = ''
		deepgramKey.value = ''
		whisperKey.value = ''
		analysisKey.value = ''
		toast('Settings saved')
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err)
	} finally {
		busy.value = false
	}
}

async function test(target: SttProvider | 'analysis'): Promise<void> {
	busy.value = true
	try {
		const typedKeys: Record<string, string> = {
			mistral: mistralKey.value,
			deepgram: deepgramKey.value,
			whisper: whisperKey.value,
			analysis: analysisKey.value,
		}
		const typed = typedKeys[target] ?? ''
		const baseUrls: Record<string, string> = {
			analysis: analysisBaseUrl.value.trim(),
			whisper: whisperBaseUrl.value.trim(),
			vosk: voskUrl.value.trim(),
		}
		const baseUrl = baseUrls[target]
		testResults.value = {
			...testResults.value,
			[target]: await api.testProvider(target, typed.trim() || undefined, baseUrl),
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
	return configured ? `configured — ${hint} (type to replace)` : 'Paste API key'
}
</script>

<template>
	<div class="cz-page">
		<div class="cz-pagehead">
			<div>
				<h2>Speech &amp; AI settings</h2>
				<p class="cz-muted" style="margin: 4px 0 0">
					API keys are stored encrypted in Nextcloud and never reach browsers or table phones.
				</p>
			</div>
			<CzButton variant="primary" :disabled="busy || !summary" @click="save">
				{{ busy ? 'Saving…' : 'Save settings' }}
			</CzButton>
		</div>

		<div v-if="error" class="cz-error">{{ error }}</div>
		<CzSkeleton v-if="!summary && !error" :rows="3" :height="120" />

		<template v-if="summary">
			<div class="cz-tabs" role="tablist">
				<button
					v-for="item in TABS"
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
					<h3>Transcription</h3>
				</div>

				<div class="cz-row" style="margin-bottom: 16px">
					<label class="cz-radiocard" :class="{ 'cz-radiocard--checked': sttProvider === 'mistral' }">
						<input v-model="sttProvider" type="radio" value="mistral" />
						Mistral (Voxtral)
					</label>
					<label class="cz-radiocard" :class="{ 'cz-radiocard--checked': sttProvider === 'deepgram' }">
						<input v-model="sttProvider" type="radio" value="deepgram" />
						Deepgram
					</label>
					<label class="cz-radiocard" :class="{ 'cz-radiocard--checked': sttProvider === 'whisper' }">
						<input v-model="sttProvider" type="radio" value="whisper" />
						Whisper (OpenAI-compatible)
					</label>
					<label class="cz-radiocard" :class="{ 'cz-radiocard--checked': sttProvider === 'vosk' }">
						<input v-model="sttProvider" type="radio" value="vosk" />
						Vosk (offline)
					</label>
				</div>

				<p class="cz-muted" style="font-size: 0.8125rem; margin: -6px 0 14px">
					{{ CAPTION_NOTE[sttProvider] }}
					Captions are provisional — the canonical transcript is always produced from
					the complete recording after the round.
				</p>

				<div v-if="sttProvider === 'mistral'" class="cz-fieldgrid">
					<div class="cz-field">
						<label>Mistral API key</label>
						<div class="cz-row" style="flex-wrap: nowrap">
							<input
								v-model="mistralKey"
								type="password"
								autocomplete="off"
								style="flex: 1"
								:placeholder="keyPlaceholder(summary.stt.mistral_configured, summary.stt.mistral_key_hint)" />
							<CzButton small :disabled="busy" @click="test('mistral')">Test</CzButton>
						</div>
						<span v-if="testResults.mistral" class="cz-pill" :class="testResults.mistral.ok ? 'cz-pill--green' : 'cz-pill--orange'" style="text-transform: none; align-self: flex-start">
							<SvgIcon :path="testResults.mistral.ok ? mdiCheck : mdiClose" :size="14" />
							{{ testResults.mistral.message }}
						</span>
					</div>
					<div class="cz-field" style="grid-column: span 2">
						<div class="cz-modelhead">
							<span>Live transcription (provisional captions)</span>
							<span>Final transcription (canonical)</span>
						</div>
						<div class="cz-modelrow">
							<input v-model="mistralLiveModel" type="text" placeholder="voxtral-mini-transcribe-realtime-2602" aria-label="Live transcription model" />
							<input v-model="mistralBatchModel" type="text" placeholder="voxtral-mini-latest" aria-label="Final transcription model" />
						</div>
						<div class="cz-modelhead cz-modelhead--hint">
							<span>Voxtral Realtime. Billed separately from the final transcription.</span>
							<span>Used for the canonical transcript after each round.</span>
						</div>
					</div>
				</div>
				<div v-else-if="sttProvider === 'deepgram'" class="cz-fieldgrid">
					<div class="cz-field">
						<label>Deepgram API key</label>
						<div class="cz-row" style="flex-wrap: nowrap">
							<input
								v-model="deepgramKey"
								type="password"
								autocomplete="off"
								style="flex: 1"
								:placeholder="keyPlaceholder(summary.stt.deepgram_configured, summary.stt.deepgram_key_hint)" />
							<CzButton small :disabled="busy" @click="test('deepgram')">Test</CzButton>
						</div>
						<span v-if="testResults.deepgram" class="cz-pill" :class="testResults.deepgram.ok ? 'cz-pill--green' : 'cz-pill--orange'" style="text-transform: none; align-self: flex-start">
							<SvgIcon :path="testResults.deepgram.ok ? mdiCheck : mdiClose" :size="14" />
							{{ testResults.deepgram.message }}
						</span>
					</div>
					<div class="cz-field" style="grid-column: span 2">
						<div class="cz-modelhead">
							<span>Live transcription (provisional captions)</span>
							<span>Final transcription (canonical)</span>
						</div>
						<div class="cz-modelrow">
							<input v-model="deepgramLiveModel" type="text" placeholder="nova-3" aria-label="Live transcription model" />
							<input v-model="deepgramBatchModel" type="text" placeholder="nova-3" aria-label="Final transcription model" />
						</div>
						<div class="cz-modelhead cz-modelhead--hint">
							<span>Streams natively and carries speaker labels.</span>
							<span>Used for the canonical transcript after each round.</span>
						</div>
					</div>
					<div class="cz-field" style="grid-column: span 2">
						<label>Live caption endpoint</label>
						<input v-model="deepgramLiveUrl" type="text" placeholder="wss://api.deepgram.com/v1/listen" />
						<span class="cz-muted" style="font-size: 0.78rem">
							Any server speaking Deepgram's streaming protocol works here — for
							example a self-hosted WhisperLiveKit, which keeps captions on your
							own infrastructure.
						</span>
					</div>
				</div>

				<div v-else-if="sttProvider === 'whisper'" class="cz-fieldgrid">
					<div class="cz-field" style="grid-column: span 2">
						<label>Endpoint base URL</label>
						<input v-model="whisperBaseUrl" type="text" placeholder="https://api.openai.com/v1" />
						<span class="cz-muted" style="font-size: 0.78rem">
							Any OpenAI-compatible transcription endpoint: OpenAI itself, or a server you
							run (Speaches, whisper.cpp, LocalAI, vLLM, WhisperX). With your own server
							the audio never leaves your infrastructure.
						</span>
					</div>
					<div class="cz-field" style="grid-column: span 2">
						<div class="cz-modelhead">
							<span>Live transcription (provisional captions)</span>
							<span>Final transcription (canonical)</span>
						</div>
						<div class="cz-modelrow">
							<input v-model="whisperLiveModel" type="text" placeholder="same as final" aria-label="Live transcription model" />
							<input v-model="whisperBatchModel" type="text" placeholder="whisper-1" aria-label="Final transcription model" />
						</div>
						<div class="cz-modelhead cz-modelhead--hint">
							<span>Optional — captions re-transcribe a rolling window every few
								seconds, so a smaller model keeps up more cheaply. Empty reuses the
								final model.</span>
							<span>A name containing “diarize” (e.g. gpt-4o-transcribe-diarize) is
								requested in diarized mode and returns speaker labels.</span>
						</div>
					</div>
					<div class="cz-field">
						<label>API key (optional)</label>
						<div class="cz-row" style="flex-wrap: nowrap">
							<input
								v-model="whisperKey"
								type="password"
								autocomplete="off"
								style="flex: 1"
								:placeholder="keyPlaceholder(summary.stt.whisper_configured, summary.stt.whisper_key_hint)" />
							<CzButton small :disabled="busy" @click="test('whisper')">Test</CzButton>
						</div>
						<span v-if="testResults.whisper" class="cz-pill" :class="testResults.whisper.ok ? 'cz-pill--green' : 'cz-pill--orange'" style="text-transform: none; align-self: flex-start">
							<SvgIcon :path="testResults.whisper.ok ? mdiCheck : mdiClose" :size="14" />
							{{ testResults.whisper.message }}
						</span>
						<span class="cz-muted" style="font-size: 0.78rem">
							Required by OpenAI; most self-hosted servers need none.
						</span>
					</div>
					<div class="cz-field" style="grid-column: span 2">
						<span class="cz-muted" style="font-size: 0.78rem">
							<strong>No speaker separation.</strong> Standard Whisper returns text with
							timestamps but does not say who spoke, so transcripts and report quotes
							appear without speaker labels. Servers that add diarization (WhisperX-based,
							or OpenAI's diarizing model) are used automatically when they provide it.
						</span>
					</div>
				</div>

				<div v-else class="cz-fieldgrid">
					<div class="cz-field" style="grid-column: span 2">
						<label>Vosk server URL</label>
						<div class="cz-row" style="flex-wrap: nowrap">
							<input v-model="voskUrl" type="text" style="flex: 1" placeholder="ws://localhost:2700" />
							<CzButton small :disabled="busy" @click="test('vosk')">Test</CzButton>
						</div>
						<span v-if="testResults.vosk" class="cz-pill" :class="testResults.vosk.ok ? 'cz-pill--green' : 'cz-pill--orange'" style="text-transform: none; align-self: flex-start">
							<SvgIcon :path="testResults.vosk.ok ? mdiCheck : mdiClose" :size="14" />
							{{ testResults.vosk.message }}
						</span>
						<span class="cz-muted" style="font-size: 0.78rem">
							A vosk-server instance you run (for example the alphacep/kaldi-en image on
							port 2700). No API key, no internet: audio never leaves your network.
						</span>
					</div>
					<div class="cz-field" style="grid-column: span 2">
						<label>Model for each language</label>
						<span class="cz-muted" style="font-size: 0.78rem; margin-bottom: 10px">
							Vosk needs its own model per language, and one server holds several. The
							language you choose for an assembly picks the model. Type the model
							<strong>name</strong> — switching model is editing this name. Leave a
							language empty until you need it; download a model with
							<code>scripts/vosk-model.sh &lt;name&gt;</code>.
						</span>
						<div class="cz-modelhead" style="grid-template-columns: 78px 1fr 1fr">
							<span>Language</span>
							<span>Live transcription (provisional captions)</span>
							<span>Final transcription (canonical)</span>
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
								placeholder="not configured"
								:aria-label="`Live caption model for ${lang.label}`" />
							<input
								v-model="voskModels[lang.code].final"
								type="text"
								placeholder="same as live"
								:aria-label="`Final transcript model for ${lang.label}`" />
						</div>
						<span class="cz-muted" style="font-size: 0.78rem; margin-top: 6px">
							A blank final model reuses the live one. A language left entirely blank falls
							back to whatever model the server started with, so a half-filled table never
							stops a recording being transcribed.
						</span>
					</div>
					<div class="cz-field">
						<label>Model label (optional)</label>
						<input v-model="voskBatchModel" type="text" placeholder="vosk-model-small-it-0.22" />
						<span class="cz-muted" style="font-size: 0.78rem">
							Recorded with the transcript for reference, and used as the model only for a
							language with no row above.
						</span>
					</div>
					<div class="cz-field" style="grid-column: span 2">
						<span class="cz-muted" style="font-size: 0.78rem">
							<strong>Offline, but plainer output.</strong> Vosk returns lower-case text
							without punctuation and does not separate speakers. It is the right choice
							when nothing may leave the premises; Deepgram or a diarizing Whisper server
							give a far more readable assembly record.
						</span>
					</div>
				</div>

				<div class="cz-row" style="gap: 24px; margin-top: 4px">
					<label style="display: flex; align-items: center; gap: 8px; cursor: pointer">
						<input v-model="liveEnabled" type="checkbox" /> Live transcription (provisional captions)
					</label>
					<label style="display: flex; align-items: center; gap: 8px; cursor: pointer">
						<input v-model="batchEnabled" type="checkbox" /> Final transcription (canonical)
					</label>
				</div>
				<span class="cz-muted" style="font-size: 0.78rem; display: block; margin-top: 8px">
					<template v-if="liveEnabled && batchEnabled">
						Tables see captions while they talk, and each recording is transcribed again
						afterwards from the complete audio. The final transcript is the record and the
						one the analysis reads.
					</template>
					<template v-else-if="batchEnabled">
						No captions during the round. Each recording is transcribed after it is
						uploaded, and that transcript is the record.
					</template>
					<template v-else-if="liveEnabled">
						<strong>The captions are the record.</strong> Nothing is transcribed a second
						time, so the analysis reads what was captured live — quicker and much cheaper,
						but captions can miss speech the engine could not keep up with. The audio is
						kept, so any table can be transcribed properly later from its Files tab.
					</template>
					<template v-else>
						<strong style="color: var(--cz-danger)">Nothing will be transcribed.</strong> Recordings are
						stored as audio and nothing else: no transcript, no analysis, and an empty
						report. Tick at least one box unless you only want the audio.
					</template>
				</span>
			</div>

			<div v-show="tab === 'ai'" class="cz-card">
				<div class="cz-row" style="margin-bottom: 4px">
					<SvgIcon :path="mdiBrain" :size="22" style="color: var(--cz-primary)" />
					<h3>AI analysis</h3>
				</div>
				<p class="cz-muted" style="font-size: 0.845rem; margin-bottom: 14px">
					Any OpenAI-compatible endpoint works: Mistral (default), Ollama Cloud, a remote Ollama server, vLLM…
				</p>
				<label style="display: flex; align-items: center; gap: 8px; cursor: pointer; margin-bottom: 14px">
					<input v-model="analysisEnabled" type="checkbox" />
					Run analysis automatically after each table is transcribed
				</label>
				<div class="cz-fieldgrid">
					<div class="cz-field" style="grid-column: span 2">
						<label>Base URL</label>
						<input v-model="analysisBaseUrl" type="text" placeholder="https://api.mistral.ai/v1" />
					</div>
					<div class="cz-field">
						<label>Model</label>
						<input v-model="analysisModel" type="text" placeholder="mistral-large-latest" />
					</div>
					<div class="cz-field">
						<label>API key</label>
						<div class="cz-row" style="flex-wrap: nowrap">
							<input
								v-model="analysisKey"
								type="password"
								autocomplete="off"
								style="flex: 1"
								:placeholder="keyPlaceholder(summary.analysis.configured, summary.analysis.key_hint)" />
							<CzButton small :disabled="busy" @click="test('analysis')">Test</CzButton>
						</div>
						<span v-if="testResults.analysis" class="cz-pill" :class="testResults.analysis.ok ? 'cz-pill--green' : 'cz-pill--orange'" style="text-transform: none; align-self: flex-start">
							<SvgIcon :path="testResults.analysis.ok ? mdiCheck : mdiClose" :size="14" />
							{{ testResults.analysis.message }}
						</span>
					</div>
				</div>

				<div class="cz-field" style="margin-top: 12px">
					<label>Additional analysis instructions (optional)</label>
					<textarea
						v-model="analysisExtra"
						rows="4"
						placeholder="E.g. Focus on transport and housing topics. Use formal Italian. Treat 'PUMS' as the city's mobility plan."></textarea>
					<span class="cz-muted" style="font-size: 0.78rem">
						Appended to the built-in prompts for table and round analysis. The output
						format and the mandatory evidence links cannot be overridden.
					</span>
				</div>

				<button
					type="button"
					class="cz-linklike"
					style="background: none; border: none; padding: 0; color: var(--cz-primary); cursor: pointer; font-size: 0.8125rem"
					@click="showPrompts = !showPrompts">
					{{ showPrompts ? 'Hide built-in prompts' : 'Show the built-in prompts your instructions are appended to' }}
				</button>
				<div v-if="showPrompts && summary.analysis.default_prompts" style="margin-top: 10px">
					<p class="cz-muted" style="font-size: 0.75rem; margin-bottom: 4px">TABLE ANALYSIS (read-only)</p>
					<pre class="cz-promptbox">{{ summary.analysis.default_prompts.table }}</pre>
					<p class="cz-muted" style="font-size: 0.75rem; margin: 10px 0 4px">ROUND AGGREGATION (read-only)</p>
					<pre class="cz-promptbox">{{ summary.analysis.default_prompts.round }}</pre>
				</div>
			</div>

			<div v-show="tab === 'general'" class="cz-card">
				<div class="cz-row" style="margin-bottom: 4px">
					<SvgIcon :path="mdiDeleteClockOutline" :size="22" style="color: var(--cz-primary)" />
					<h3>Audio retention</h3>
				</div>
				<p class="cz-muted" style="font-size: 0.845rem; margin-bottom: 14px">
					Delete the raw audio of an assembly this many days after it is
					<strong>closed</strong>. Transcripts, findings and reports are never
					removed by this — only the recordings. Individual assemblies can
					override it, and organizers can always delete audio sooner from the
					Files tab.
				</p>
				<div class="cz-field" style="max-width: 260px">
					<label>Days to keep audio after closing</label>
					<input v-model.number="retentionDays" type="number" min="0" max="3650" />
					<p class="cz-muted" style="font-size: 0.78rem; margin-top: 6px">
						{{
							Number(retentionDays) > 0
								? `Audio is deleted ${retentionDays} days after an assembly is closed. Table phones are told this before recording.`
								: 'Audio is kept until someone deletes it. Table phones are told this before recording.'
						}}
					</p>
				</div>
			</div>

			<div v-show="tab === 'general'" class="cz-card">
				<div class="cz-row" style="margin-bottom: 4px">
					<SvgIcon :path="mdiImageOutline" :size="22" style="color: var(--cz-primary)" />
					<h3>Organization</h3>
				</div>
				<p class="cz-muted" style="font-size: 0.845rem; margin-bottom: 14px">
					Name and logo appear on the header and footer of PDF reports.
					Logo: PNG or JPEG, up to 1&nbsp;MB.
				</p>
				<div class="cz-field" style="max-width: 420px">
					<label>Organization name</label>
					<input v-model="orgName" type="text" placeholder="Democracy Innovators" />
				</div>
				<div class="cz-row" style="align-items: center; gap: 16px">
					<img
						v-if="logoSet"
						:src="logoUrl()"
						alt="Organization logo"
						style="max-height: 56px; max-width: 200px; border: 1px solid var(--cz-border); border-radius: 8px; padding: 6px; background: #fff" />
					<label class="cz-btn cz-btn--secondary" style="cursor: pointer">
						{{ logoSet ? 'Replace logo' : 'Upload logo' }}
						<input type="file" accept="image/png,image/jpeg" style="display: none" @change="uploadLogo" />
					</label>
					<CzButton v-if="logoSet" small variant="tertiary" :disabled="busy" @click="removeLogo">
						Remove
					</CzButton>
				</div>
			</div>
		</template>
	</div>
</template>
