// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The built-in Vosk engine is managed from Settings: pick the mode, install
 * and remove models, pick them per language. Before this an admin typed model
 * names into free-text boxes and downloaded them with a shell script.
 */
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SettingsView from '../../frontend/src/components/SettingsView.vue'
import { mountWithI18n } from './support/mount'

const getProviders = vi.fn()
const voskModels = vi.fn()
const voskModelInstall = vi.fn()
const voskModelCancel = vi.fn()
const voskModelRemove = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: {
		getProviders: (...a: unknown[]) => getProviders(...a),
		voskModels: (...a: unknown[]) => voskModels(...a),
		voskModelInstall: (...a: unknown[]) => voskModelInstall(...a),
		voskModelCancel: (...a: unknown[]) => voskModelCancel(...a),
		voskModelRemove: (...a: unknown[]) => voskModelRemove(...a),
		updateProviders: vi.fn(),
		testProvider: vi.fn(),
	},
	ApiError: class extends Error {},
	BASE: '',
}))

function summary(mode: 'builtin' | 'server', saved: Record<string, { live: string; final: string }> = {}) {
	return {
		stt: {
			provider: 'vosk',
			live_enabled: true,
			batch_enabled: true,
			vosk_url: 'ws://localhost:2700',
			vosk_mode: mode,
			vosk_language_models: saved,
			vosk_batch_model: '',
		},
		analysis: { base_url: '', model: '', enabled: true, extra_instructions: '', default_prompts: { table: '', round: '' } },
		facilitator: null,
	}
}

function catalog(progress: unknown = null, installed = true) {
	return {
		installed: installed
			? [
					{ name: 'vosk-model-small-en-us-0.15', language: 'en', kind: 'small', size_bytes: 41943040, usable: true },
					{ name: 'my-custom-it', language: 'it', kind: 'custom', size_bytes: 10485760, usable: true },
				]
			: [],
		available: [
			{ name: 'vosk-model-small-en-us-0.15', language: 'en', kind: 'small', size_mb: 40, progress: null },
			{ name: 'vosk-model-small-it-0.22', language: 'it', kind: 'small', size_mb: 48, progress },
		],
		engine: { running: true, port: 2700, loaded: [], in_use: {}, last_error: null, memory_available_bytes: 524288000 },
		memory_available_bytes: 524288000,
	}
}

async function mountSettings() {
	const wrapper = mountWithI18n(SettingsView)
	await flushPromises()
	return wrapper
}

beforeEach(() => {
	vi.clearAllMocks()
	getProviders.mockResolvedValue(summary('builtin'))
	voskModels.mockResolvedValue(catalog())
})

afterEach(() => {
	vi.useRealTimers()
})

describe('Vosk mode switch', () => {
	it('shows the URL only for a server', async () => {
		const wrapper = await mountSettings()
		expect(wrapper.text()).not.toContain('Vosk server URL')

		await wrapper.findAll('[data-test="vosk-mode"] input')[1].setValue(true)

		expect(wrapper.text()).toContain('Vosk server URL')
		expect(wrapper.find('[data-test="vosk-models"]').exists()).toBe(false)
	})
})

describe('Vosk model manager', () => {
	it('lists installed and available models with their actions', async () => {
		const wrapper = await mountSettings()

		const rows = wrapper.findAll('[data-test="model-row"]')
		expect(rows).toHaveLength(3)
		expect(wrapper.text()).toContain('500 MB free for models in this container')
		expect(wrapper.text()).toContain('Engine running')
		expect(wrapper.findAll('[data-test="model-remove"]')).toHaveLength(2)
		expect(wrapper.findAll('[data-test="model-install"]')).toHaveLength(1)
	})

	it('installs, then shows progress on the next poll', async () => {
		vi.useFakeTimers()
		voskModelInstall.mockResolvedValue({ queued: true, name: 'vosk-model-small-it-0.22' })
		const wrapper = await mountSettings()

		voskModels.mockResolvedValue(
			catalog({ phase: 'downloading', received: 24, total: 48, error: null, started_at: 1 }),
		)
		await wrapper.find('[data-test="model-install"]').trigger('click')
		await flushPromises()
		expect(voskModelInstall).toHaveBeenCalledWith('vosk-model-small-it-0.22')
		expect(wrapper.find('[data-test="model-progress"]').text()).toContain('downloading 50%')

		voskModels.mockResolvedValue(
			catalog({ phase: 'downloading', received: 48, total: 48, error: null, started_at: 1 }),
		)
		await vi.advanceTimersByTimeAsync(3000)
		expect(wrapper.find('[data-test="model-progress"]').text()).toContain('100%')
	})

	it('confirms before it removes', async () => {
		voskModelRemove.mockResolvedValue({ removed: true, name: 'my-custom-it', freed_bytes: 1 })
		const wrapper = await mountSettings()

		await wrapper.findAll('[data-test="model-remove"]')[1].trigger('click')
		expect(voskModelRemove).not.toHaveBeenCalled()
		expect(wrapper.text()).toContain('Remove my-custom-it?')

		await wrapper.find('[data-test="model-remove-confirm"]').trigger('click')
		await flushPromises()
		expect(voskModelRemove).toHaveBeenCalledWith('my-custom-it')
	})

	it('offers only installed models in the pickers, plus a saved one that is gone', async () => {
		getProviders.mockResolvedValue(summary('builtin', { it: { live: 'gone-model', final: '' } }))
		const wrapper = await mountSettings()

		const live = wrapper.find('select[aria-label="Live caption model for English"]')
		expect(live.findAll('option').map((o) => o.attributes('value'))).toEqual(['', 'vosk-model-small-en-us-0.15'])

		const italian = wrapper.find('select[aria-label="Live caption model for Italiano"]')
		expect(italian.findAll('option').map((o) => o.attributes('value'))).toEqual(['', 'my-custom-it', 'gone-model'])
		expect(italian.text()).toContain('gone-model (not installed)')
	})
})
