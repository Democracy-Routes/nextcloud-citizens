// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/** The Settings form, shared by every card on the page.
 *
 * One `form` holds every value the PUT /admin/providers payload can carry,
 * keyed exactly as the server names them. Each card owns a list of those
 * keys (CARD_KEYS): its Save button lights up when one of its keys differs
 * from the snapshot taken at the last load or save, and its save sends only
 * those keys — so an admin who came to change the retention never commits
 * what was sitting half-typed on another card, which is what the single
 * page-wide Save used to do.
 *
 * Secrets (API keys) are never loaded back; they are sent only when retyped,
 * and only with the card they belong to.
 */
import { computed, inject, provide, reactive, ref, type InjectionKey } from 'vue'
import { api } from '../../api'
import { describeError } from '../../errors'
import type { ProvidersSummary, SttProvider, VoskMode } from '../../types'

export const STT_PROVIDERS: readonly SttProvider[] = ['mistral', 'deepgram', 'whisper', 'vosk']

/** the languages an assembly can be run in (AssemblyWizard.vue). Vosk needs
 * its own model for each, so every one gets a row whether or not it is
 * configured. Labels are endonyms — each language names itself — so they
 * are not translated. */
export const ASSEMBLY_LANGUAGES: ReadonlyArray<{ code: string; label: string }> = [
	{ code: 'en', label: 'English' },
	{ code: 'it', label: 'Italiano' },
	{ code: 'de', label: 'Deutsch' },
	{ code: 'fr', label: 'Français' },
	{ code: 'es', label: 'Español' },
]

export type FacilitatorLevel = 'off' | 'light' | 'normal' | 'active'
export const FACILITATOR_LEVELS: readonly FacilitatorLevel[] = ['off', 'light', 'normal', 'active']

export interface SettingsForm {
	stt_provider: SttProvider
	stt_live_enabled: boolean
	stt_batch_enabled: boolean
	mistral_live_model: string
	mistral_batch_model: string
	deepgram_live_model: string
	deepgram_batch_model: string
	deepgram_live_url: string
	whisper_base_url: string
	whisper_batch_model: string
	whisper_live_model: string
	vosk_url: string
	vosk_mode: VoskMode
	vosk_batch_model: string
	/** per-provider caps on concurrent transcription work — live caption
	 * sessions and final (batch) transcriptions as independent pools,
	 * server-wide. Uncapped, a plenary room of phones can saturate a
	 * self-hosted Vosk server or a provider's rate limit. */
	concurrency: Record<SttProvider, { live: number; batch: number }>
	/** language code -> model names; encoded as JSON in the payload */
	vosk_language_models: Record<string, { live: string; final: string }>
	analysis_base_url: string
	analysis_model: string
	analysis_enabled: boolean
	analysis_extra_instructions: string
	facilitator_level: FacilitatorLevel
	facilitator_base_url: string
	facilitator_model: string
	facilitator_interval_minutes: number
	facilitator_dominance_percent: number
	facilitator_silence_seconds: number
	organization_name: string
	audio_retention_days: number
	consent_controller: string
	consent_contact: string
	org_address: string
	org_dpo: string
	org_hosting: string
	org_authority: string
}

export type SecretKey =
	| 'mistral_api_key'
	| 'deepgram_api_key'
	| 'whisper_api_key'
	| 'analysis_api_key'
	| 'facilitator_api_key'

export const SECRET_KEYS: readonly SecretKey[] = [
	'mistral_api_key',
	'deepgram_api_key',
	'whisper_api_key',
	'analysis_api_key',
	'facilitator_api_key',
]

/** A payload key: one the server accepts in PUT /admin/providers. */
export type PayloadKey = string

export type CardId =
	| 'service'
	| 'mistral'
	| 'deepgram'
	| 'whisper'
	| 'voskEngine'
	| 'voskLanguages'
	| 'limits'
	| 'analysis'
	| 'facilitator'
	| 'org'
	| 'retention'
	| 'branding'

/** Which payload keys each card owns. `limits` depends on the selected
 * provider and is computed (see `cardKeys`). */
export const CARD_KEYS: Record<Exclude<CardId, 'limits'>, PayloadKey[]> = {
	service: ['stt_provider', 'stt_live_enabled', 'stt_batch_enabled'],
	mistral: ['mistral_live_model', 'mistral_batch_model', 'mistral_api_key'],
	deepgram: ['deepgram_live_model', 'deepgram_batch_model', 'deepgram_live_url', 'deepgram_api_key'],
	whisper: ['whisper_base_url', 'whisper_batch_model', 'whisper_live_model', 'whisper_api_key'],
	voskEngine: ['vosk_mode', 'vosk_url'],
	voskLanguages: ['vosk_language_models', 'vosk_batch_model'],
	analysis: [
		'analysis_base_url',
		'analysis_model',
		'analysis_enabled',
		'analysis_extra_instructions',
		'analysis_api_key',
	],
	facilitator: [
		'facilitator_level',
		'facilitator_base_url',
		'facilitator_model',
		'facilitator_interval_minutes',
		'facilitator_dominance_percent',
		'facilitator_silence_seconds',
		'facilitator_api_key',
	],
	org: ['consent_controller', 'consent_contact', 'org_address', 'org_dpo', 'org_hosting', 'org_authority'],
	retention: ['audio_retention_days'],
	branding: ['organization_name'],
}

export function limitsKeys(provider: SttProvider): PayloadKey[] {
	return [`stt_concurrency_${provider}_live`, `stt_concurrency_${provider}_batch`]
}

const DEFAULT_CONCURRENCY: Record<SttProvider, { live: number; batch: number }> = {
	deepgram: { live: 10, batch: 5 },
	mistral: { live: 15, batch: 5 },
	vosk: { live: 5, batch: 2 },
	whisper: { live: 2, batch: 1 },
}

function clampCap(value: number): number {
	return Math.min(100, Math.max(1, Number(value) || 1))
}

function emptyForm(): SettingsForm {
	return {
		stt_provider: 'mistral',
		stt_live_enabled: true,
		stt_batch_enabled: true,
		mistral_live_model: '',
		mistral_batch_model: '',
		deepgram_live_model: '',
		deepgram_batch_model: '',
		deepgram_live_url: '',
		whisper_base_url: '',
		whisper_batch_model: '',
		whisper_live_model: '',
		vosk_url: '',
		vosk_mode: 'server',
		vosk_batch_model: '',
		concurrency: JSON.parse(JSON.stringify(DEFAULT_CONCURRENCY)),
		vosk_language_models: Object.fromEntries(
			ASSEMBLY_LANGUAGES.map((l) => [l.code, { live: '', final: '' }]),
		),
		analysis_base_url: '',
		analysis_model: '',
		analysis_enabled: true,
		analysis_extra_instructions: '',
		facilitator_level: 'off',
		facilitator_base_url: '',
		facilitator_model: '',
		facilitator_interval_minutes: 4,
		facilitator_dominance_percent: 60,
		facilitator_silence_seconds: 90,
		organization_name: '',
		audio_retention_days: 0,
		consent_controller: '',
		consent_contact: '',
		org_address: '',
		org_dpo: '',
		org_hosting: '',
		org_authority: '',
	}
}

/** The flat PUT payload the form represents — every key, trimmed and
 * clamped the way the server expects (byte-identical to what the page sent
 * before it was split into cards). */
export function payloadOf(form: SettingsForm): Record<PayloadKey, unknown> {
	const payload: Record<PayloadKey, unknown> = {
		stt_provider: form.stt_provider,
		stt_live_enabled: form.stt_live_enabled,
		stt_batch_enabled: form.stt_batch_enabled,
		mistral_live_model: form.mistral_live_model.trim(),
		mistral_batch_model: form.mistral_batch_model.trim(),
		deepgram_live_model: form.deepgram_live_model.trim(),
		deepgram_batch_model: form.deepgram_batch_model.trim(),
		deepgram_live_url: form.deepgram_live_url.trim(),
		whisper_base_url: form.whisper_base_url.trim(),
		whisper_batch_model: form.whisper_batch_model.trim(),
		whisper_live_model: form.whisper_live_model.trim(),
		vosk_url: form.vosk_url.trim(),
		vosk_mode: form.vosk_mode,
		vosk_batch_model: form.vosk_batch_model.trim(),
		vosk_language_models: JSON.stringify(
			Object.fromEntries(
				Object.entries(form.vosk_language_models)
					.map(([code, row]) => [code, { live: row.live.trim(), final: row.final.trim() }])
					// a language with neither model set is simply not configured
					.filter(([, row]) => (row as { live: string; final: string }).live
						|| (row as { live: string; final: string }).final),
			),
		),
		analysis_base_url: form.analysis_base_url.trim(),
		analysis_model: form.analysis_model.trim(),
		analysis_enabled: form.analysis_enabled,
		analysis_extra_instructions: form.analysis_extra_instructions.trim(),
		facilitator_level: form.facilitator_level,
		facilitator_base_url: form.facilitator_base_url.trim(),
		facilitator_model: form.facilitator_model.trim(),
		facilitator_interval_minutes: Number(form.facilitator_interval_minutes) || 4,
		facilitator_dominance_percent: Number(form.facilitator_dominance_percent) || 60,
		facilitator_silence_seconds: Number(form.facilitator_silence_seconds) || 90,
		organization_name: form.organization_name.trim(),
		audio_retention_days: Number(form.audio_retention_days) || 0,
		consent_controller: form.consent_controller.trim(),
		consent_contact: form.consent_contact.trim(),
		org_address: form.org_address.trim(),
		org_dpo: form.org_dpo.trim(),
		org_hosting: form.org_hosting.trim(),
		org_authority: form.org_authority.trim(),
	}
	for (const provider of STT_PROVIDERS) {
		// clamp locally so a cleared field round-trips as the minimum rather
		// than a 422 from the server
		payload[`stt_concurrency_${provider}_live`] = clampCap(form.concurrency[provider].live)
		payload[`stt_concurrency_${provider}_batch`] = clampCap(form.concurrency[provider].batch)
	}
	return payload
}

export type TestTarget = SttProvider | 'analysis' | 'facilitator'

export function createSettingsForm() {
	const summary = ref<ProvidersSummary | null>(null)
	const loadError = ref('')
	const form = reactive<SettingsForm>(emptyForm())
	const secrets = reactive<Record<SecretKey, string>>({
		mistral_api_key: '',
		deepgram_api_key: '',
		whisper_api_key: '',
		analysis_api_key: '',
		facilitator_api_key: '',
	})
	/** the payload as it stood at the last load or save, per key (JSON) */
	const saved = ref<Record<PayloadKey, string>>({})
	/** the card whose save or test is in flight ('' when none) */
	const busyCard = ref('')
	const errors = reactive<Record<string, string>>({})
	const testResults = reactive<Record<string, { ok: boolean; message: string }>>({})

	function snapshotOf(payload: Record<PayloadKey, unknown>): Record<PayloadKey, string> {
		return Object.fromEntries(Object.entries(payload).map(([k, v]) => [k, JSON.stringify(v)]))
	}

	/** Every field defaults when the server does not send it: a summary from
	 * an older server (or a sparse test fixture) must not break the page. */
	async function load(): Promise<void> {
		const s = await api.getProviders()
		summary.value = s
		form.stt_provider = s.stt.provider ?? 'mistral'
		form.stt_live_enabled = s.stt.live_enabled ?? true
		form.stt_batch_enabled = s.stt.batch_enabled ?? true
		form.mistral_live_model = s.stt.mistral_live_model ?? ''
		form.mistral_batch_model = s.stt.mistral_batch_model ?? ''
		form.deepgram_live_model = s.stt.deepgram_live_model ?? ''
		form.deepgram_batch_model = s.stt.deepgram_batch_model ?? ''
		form.deepgram_live_url = s.stt.deepgram_live_url ?? ''
		form.whisper_base_url = s.stt.whisper_base_url ?? ''
		form.whisper_batch_model = s.stt.whisper_batch_model ?? ''
		form.whisper_live_model = s.stt.whisper_live_model ?? ''
		form.vosk_url = s.stt.vosk_url ?? ''
		form.vosk_mode = s.stt.vosk_mode ?? 'server'
		form.vosk_batch_model = s.stt.vosk_batch_model ?? ''
		for (const provider of STT_PROVIDERS) {
			const stt = s.stt as unknown as Record<string, number | undefined>
			form.concurrency[provider] = {
				live: stt[`stt_concurrency_${provider}_live`] ?? DEFAULT_CONCURRENCY[provider].live,
				batch: stt[`stt_concurrency_${provider}_batch`] ?? DEFAULT_CONCURRENCY[provider].batch,
			}
		}
		const stored = s.stt.vosk_language_models ?? {}
		form.vosk_language_models = Object.fromEntries(
			ASSEMBLY_LANGUAGES.map(({ code }) => [
				code,
				{ live: stored[code]?.live ?? '', final: stored[code]?.final ?? '' },
			]),
		)
		form.analysis_base_url = s.analysis.base_url ?? ''
		form.analysis_model = s.analysis.model ?? ''
		form.analysis_enabled = s.analysis.enabled ?? true
		form.analysis_extra_instructions = s.analysis.extra_instructions ?? ''
		if (s.facilitator) {
			form.facilitator_level = s.facilitator.level ?? 'off'
			form.facilitator_base_url = s.facilitator.base_url ?? ''
			form.facilitator_model = s.facilitator.model ?? ''
			form.facilitator_interval_minutes = s.facilitator.interval_minutes ?? 4
			form.facilitator_dominance_percent = s.facilitator.dominance_percent ?? 60
			form.facilitator_silence_seconds = s.facilitator.silence_seconds ?? 90
		}
		form.organization_name = s.organization_name ?? ''
		form.audio_retention_days = s.audio_retention_days ?? 0
		form.consent_controller = s.consent_controller ?? ''
		form.consent_contact = s.consent_contact ?? ''
		form.org_address = s.org_address ?? ''
		form.org_dpo = s.org_dpo ?? ''
		form.org_hosting = s.org_hosting ?? ''
		form.org_authority = s.org_authority ?? ''
		// the baseline every later edit is compared against
		saved.value = snapshotOf(payloadOf(form))
	}

	function cardKeys(card: CardId): PayloadKey[] {
		return card === 'limits' ? limitsKeys(form.stt_provider) : CARD_KEYS[card]
	}

	/** The changed keys among `keys`, plus the secrets among them that were
	 * typed. */
	function payloadFor(keys: PayloadKey[]): Record<PayloadKey, unknown> {
		const current = payloadOf(form)
		const payload: Record<PayloadKey, unknown> = {}
		for (const key of keys) {
			if (key in secrets) {
				const typed = secrets[key as SecretKey]
				if (typed) payload[key] = typed
			} else if (key in current && JSON.stringify(current[key]) !== saved.value[key]) {
				payload[key] = current[key]
			}
		}
		return payload
	}

	function isDirty(card: CardId): boolean {
		if (!summary.value) return false
		return Object.keys(payloadFor(cardKeys(card))).length > 0
	}

	const anyDirty = computed(() => {
		const cards: CardId[] = [
			'service', 'mistral', 'deepgram', 'whisper', 'voskEngine', 'voskLanguages', 'limits',
			'analysis', 'facilitator', 'org', 'retention', 'branding',
		]
		return cards.some(isDirty)
	})

	async function save(card: CardId): Promise<boolean> {
		const keys = cardKeys(card)
		const payload = payloadFor(keys)
		if (Object.keys(payload).length === 0) return true
		busyCard.value = card
		errors[card] = ''
		try {
			summary.value = await api.updateProviders(payload)
			// re-snapshot only what this card sent: another card's pending
			// edits stay pending
			const current = payloadOf(form)
			for (const key of keys) {
				if (key in secrets) secrets[key as SecretKey] = ''
				else if (key in current) saved.value[key] = JSON.stringify(current[key])
			}
			return true
		} catch (err) {
			errors[card] = describeError(err).message
			return false
		} finally {
			busyCard.value = ''
		}
	}

	async function test(target: TestTarget, card: CardId): Promise<void> {
		busyCard.value = card
		try {
			const typedKeys: Partial<Record<TestTarget, string>> = {
				mistral: secrets.mistral_api_key,
				deepgram: secrets.deepgram_api_key,
				whisper: secrets.whisper_api_key,
				analysis: secrets.analysis_api_key,
				facilitator: secrets.facilitator_api_key,
			}
			const baseUrls: Partial<Record<TestTarget, string>> = {
				analysis: form.analysis_base_url.trim(),
				facilitator: form.facilitator_base_url.trim(),
				whisper: form.whisper_base_url.trim(),
				vosk: form.vosk_url.trim(),
			}
			// the analysis test makes one real completion: with the model in
			// the form, not the saved one, or a typed replacement can never be
			// tested
			const model =
				target === 'analysis'
					? form.analysis_model.trim() || undefined
					: target === 'facilitator'
						? form.facilitator_model.trim() || undefined
						: undefined
			const typed = (typedKeys[target] ?? '').trim()
			testResults[target] = await api.testProvider(target, typed || undefined, baseUrls[target], model)
		} catch (err) {
			testResults[target] = { ok: false, message: err instanceof Error ? err.message : String(err) }
		} finally {
			busyCard.value = ''
		}
	}

	return {
		summary,
		loadError,
		form,
		secrets,
		busyCard,
		errors,
		testResults,
		anyDirty,
		load,
		cardKeys,
		payloadFor,
		isDirty,
		save,
		test,
	}
}

export type SettingsFormApi = ReturnType<typeof createSettingsForm>

const KEY: InjectionKey<SettingsFormApi> = Symbol('citizens.settings.form')

export function provideSettingsForm(): SettingsFormApi {
	const instance = createSettingsForm()
	provide(KEY, instance)
	return instance
}

export function useSettingsForm(): SettingsFormApi {
	const instance = inject(KEY)
	if (!instance) throw new Error('useSettingsForm() outside SettingsView')
	return instance
}
