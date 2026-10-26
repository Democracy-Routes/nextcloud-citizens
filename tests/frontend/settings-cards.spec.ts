// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Settings is a column of cards per tab, each with its own Save: a card only
 * sends its own keys, a typed secret travels with its own card, and an edit in
 * one card survives saving another.
 */
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SettingsView from '../../frontend/src/components/SettingsView.vue'
import catalogue from '../../frontend/src/i18n/organizer/settings.en.json'
import { mountWithI18n } from './support/mount'

const getProviders = vi.fn()
const updateProviders = vi.fn()
const voskModels = vi.fn()
const testProvider = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: {
		getProviders: (...a: unknown[]) => getProviders(...a),
		updateProviders: (...a: unknown[]) => updateProviders(...a),
		voskModels: (...a: unknown[]) => voskModels(...a),
		testProvider: (...a: unknown[]) => testProvider(...a),
	},
	ApiError: class extends Error {},
	BASE: '',
}))

function summary() {
	return {
		organization_name: 'Acme',
		audio_retention_days: 0,
		consent_controller: '',
		consent_contact: '',
		org_address: '',
		org_dpo: '',
		org_hosting: '',
		org_authority: '',
		stt: {
			provider: 'mistral',
			live_enabled: true,
			batch_enabled: true,
			mistral_configured: false,
			mistral_key_hint: '',
			mistral_live_model: 'voxtral-live',
			mistral_batch_model: 'voxtral-batch',
			deepgram_configured: false,
			deepgram_key_hint: '',
			deepgram_live_model: 'nova-3',
			deepgram_batch_model: 'nova-3',
			deepgram_live_url: '',
			whisper_configured: false,
			whisper_key_hint: '',
			whisper_base_url: '',
			whisper_batch_model: 'whisper-1',
			whisper_live_model: '',
			vosk_url: 'ws://localhost:2700',
			vosk_mode: 'builtin',
			vosk_language_models: {},
			vosk_batch_model: '',
			stt_concurrency_deepgram_live: 5,
			stt_concurrency_deepgram_batch: 5,
			stt_concurrency_mistral_live: 5,
			stt_concurrency_mistral_batch: 5,
			stt_concurrency_vosk_live: 5,
			stt_concurrency_vosk_batch: 5,
			stt_concurrency_whisper_live: 5,
			stt_concurrency_whisper_batch: 5,
		},
		analysis: {
			base_url: '',
			model: '',
			configured: false,
			key_hint: '',
			enabled: true,
			extra_instructions: '',
			default_prompts: { table: '', round: '' },
		},
		facilitator: {
			level: 'off',
			configured: false,
			own_key: false,
			interval_minutes: 5,
			dominance_percent: 70,
			silence_seconds: 120,
			base_url: '',
			model: '',
			key_hint: '',
		},
		logo_set: false,
	}
}

function catalog() {
	return {
		installed: [],
		available: [],
		engine: { running: true, port: 2700, loaded: [], in_use: {}, last_error: null, memory_available_bytes: 524288000 },
		memory_available_bytes: 524288000,
	}
}

const mounted: VueWrapper[] = []

async function mountSettings() {
	const wrapper = mountWithI18n(SettingsView)
	mounted.push(wrapper)
	await flushPromises()
	return wrapper
}

function saveIn(wrapper: VueWrapper, card: string) {
	return wrapper.get(`[data-test="${card}"] [data-test="card-save"]`)
}

async function openTab(wrapper: VueWrapper, label: string) {
	const button = wrapper.findAll('[role="tab"]').find((b) => b.text().includes(label))
	if (!button) throw new Error(`no tab "${label}"`)
	await button.trigger('click')
	await flushPromises()
}

async function setRetention(wrapper: VueWrapper, days: number) {
	await openTab(wrapper, catalogue.tabs.organisation)
	await wrapper.get('[data-test="card-retention"] input[type="number"]').setValue(days)
}

beforeEach(() => {
	vi.clearAllMocks()
	sessionStorage.clear()
	getProviders.mockResolvedValue(summary())
	updateProviders.mockResolvedValue(summary())
	voskModels.mockResolvedValue(catalog())
})

afterEach(() => {
	// the page listens on window: a left-over mount would warn in later tests
	for (const wrapper of mounted.splice(0)) wrapper.unmount()
})

describe('Settings cards', () => {
	it('every Save starts disabled', async () => {
		const wrapper = await mountSettings()
		const saves = wrapper.findAll('[data-test="card-save"]')
		expect(saves.length).toBeGreaterThan(0)
		for (const save of saves) expect(save.attributes('disabled')).toBeDefined()
	})

	it('a change in Retention enables only the Retention Save, and its save sends only that key', async () => {
		const wrapper = await mountSettings()
		await setRetention(wrapper, 30)
		expect(saveIn(wrapper, 'card-retention').attributes('disabled')).toBeUndefined()
		expect(saveIn(wrapper, 'card-org').attributes('disabled')).toBeDefined()
		expect(saveIn(wrapper, 'card-service').attributes('disabled')).toBeDefined()

		await saveIn(wrapper, 'card-retention').trigger('click')
		await flushPromises()
		expect(updateProviders).toHaveBeenCalledTimes(1)
		expect(updateProviders.mock.calls[0][0]).toEqual({ audio_retention_days: 30 })
		expect(saveIn(wrapper, 'card-retention').attributes('disabled')).toBeDefined()
	})

	it('a typed API key goes with its own card and is cleared after', async () => {
		const wrapper = await mountSettings()
		const key = wrapper.get('[data-test="card-mistral"] input[type="password"]')
		await key.setValue('sk-test')
		expect(saveIn(wrapper, 'card-mistral').attributes('disabled')).toBeUndefined()

		await saveIn(wrapper, 'card-mistral').trigger('click')
		await flushPromises()
		expect(updateProviders).toHaveBeenCalledTimes(1)
		expect(updateProviders.mock.calls[0][0]).toEqual({ mistral_api_key: 'sk-test' })
		expect((wrapper.get('[data-test="card-mistral"] input[type="password"]').element as HTMLInputElement).value).toBe('')
	})

	it("saving one card leaves another card's edits pending", async () => {
		const wrapper = await mountSettings()
		await setRetention(wrapper, 45)
		await openTab(wrapper, catalogue.tabs.transcription)
		await wrapper
			.get(`[data-test="card-mistral"] input[aria-label="${catalogue.audio.liveModelAria}"]`)
			.setValue('voxtral-new')

		await saveIn(wrapper, 'card-mistral').trigger('click')
		await flushPromises()
		expect(updateProviders).toHaveBeenCalledTimes(1)
		expect(updateProviders.mock.calls[0][0]).toEqual({ mistral_live_model: 'voxtral-new' })
		expect(saveIn(wrapper, 'card-retention').attributes('disabled')).toBeUndefined()
	})

	it("Limits shows only the selected service's pair", async () => {
		const wrapper = await mountSettings()
		expect(wrapper.findAll('[data-test="card-limits"] input[type="number"]')).toHaveLength(2)

		await wrapper.get('[data-test="card-service"] input[type="radio"][value="vosk"]').setValue()
		await flushPromises()
		expect(wrapper.findAll('[data-test="card-limits"] input[type="number"]')).toHaveLength(2)
		expect(wrapper.find('[data-test="card-vosk-engine"]').exists()).toBe(true)
		expect(wrapper.find('[data-test="card-mistral"]').exists()).toBe(false)
	})

	it('the last tab is remembered', async () => {
		sessionStorage.setItem('citizens.settings.tab', 'organisation')
		const wrapper = await mountSettings()
		const tabs = wrapper.findAll('[role="tab"]')
		const org = tabs.find((b) => b.text().includes(catalogue.tabs.organisation))
		expect(org?.attributes('aria-selected')).toBe('true')

		await openTab(wrapper, catalogue.tabs.transcription)
		expect(sessionStorage.getItem('citizens.settings.tab')).toBe('transcription')
	})

	it('the browser is warned before leaving with unsaved changes', async () => {
		const wrapper = await mountSettings()
		const clean = new Event('beforeunload', { cancelable: true })
		window.dispatchEvent(clean)
		expect(clean.defaultPrevented).toBe(false)

		await setRetention(wrapper, 30)
		const dirty = new Event('beforeunload', { cancelable: true })
		window.dispatchEvent(dirty)
		expect(dirty.defaultPrevented).toBe(true)
	})
})
