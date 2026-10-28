// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Settings > Organisation > Accounts (standalone mode only). */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { auth } from '../../frontend/src/auth'
import SettingsView from '../../frontend/src/components/SettingsView.vue'
import catalogue from '../../frontend/src/i18n/organizer/settings.en.json'
import UsersCard from '../../frontend/src/components/settings/UsersCard.vue'
import { mountWithI18n } from './support/mount'

const listUsers = vi.fn()
const createUser = vi.fn()
const updateUser = vi.fn()
const inviteUser = vi.fn()
const deleteUser = vi.fn()
const getProviders = vi.fn()
const voskModels = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: {
		listUsers: (...a: unknown[]) => listUsers(...a),
		createUser: (...a: unknown[]) => createUser(...a),
		updateUser: (...a: unknown[]) => updateUser(...a),
		inviteUser: (...a: unknown[]) => inviteUser(...a),
		deleteUser: (...a: unknown[]) => deleteUser(...a),
		getProviders: (...a: unknown[]) => getProviders(...a),
		voskModels: (...a: unknown[]) => voskModels(...a),
	},
	ApiError: class extends Error {
		status: number
		constructor(status: number, message: string) {
			super(message)
			this.status = status
		}
	},
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

function account(over: Record<string, unknown> = {}) {
	return {
		id: 'u1',
		username: 'anna',
		display_name: 'Anna Rossi',
		email: 'anna@example.org',
		email_verified: true,
		role: 'admin',
		language: 'en',
		has_password: true,
		oidc: false,
		disabled: false,
		created_at: null,
		last_login_at: null,
		...over,
	}
}

beforeEach(() => {
	vi.clearAllMocks()
	auth.config = {
		mode: 'standalone',
		version: 'x',
		login: { password: true, oidc: false },
		mail: true,
		languages: ['en'],
	}
	auth.account = account() as never
	listUsers.mockResolvedValue({
		users: [account(), account({ id: 'u2', username: 'bruno', display_name: 'Bruno', email: null, role: 'organizer', has_password: false })],
		mail: true,
	})
})

describe('UsersCard', () => {
	it('lists the accounts with role, state and the verified hint', async () => {
		const wrapper = mountWithI18n(UsersCard)
		await flushPromises()
		const anna = wrapper.get('[data-test="user-anna"]').text()
		expect(anna).toContain('anna@example.org')
		expect(anna).toContain('verified')
		expect(anna).toContain('Administrator')
		expect(anna).toContain('Active')
		const bruno = wrapper.get('[data-test="user-bruno"]').text()
		expect(bruno).toContain('Invited')
		expect(bruno).toContain('Organizer')
		expect(wrapper.find('[data-test="users-no-mail"]').exists()).toBe(false)
	})

	it('hints that mail is not configured', async () => {
		listUsers.mockResolvedValue({ users: [], mail: false })
		const wrapper = mountWithI18n(UsersCard)
		await flushPromises()
		expect(wrapper.get('[data-test="users-no-mail"]').text()).toContain('server log')
	})

	it('creates an account with the right body and says whether a mail went out', async () => {
		createUser.mockResolvedValue(account({ id: 'u3', username: 'carla', invited: true }))
		const wrapper = mountWithI18n(UsersCard)
		await flushPromises()
		await wrapper.get('[data-test="add-username"]').setValue('carla')
		await wrapper.get('[data-test="add-display-name"]').setValue('Carla')
		await wrapper.get('[data-test="add-email"]').setValue('carla@example.org')
		await wrapper.get('[data-test="add-role"]').setValue('admin')
		await wrapper.get('[data-test="add-language"]').setValue('de')
		await wrapper.get('[data-test="user-add-form"]').trigger('submit')
		await flushPromises()
		expect(createUser).toHaveBeenCalledWith({
			username: 'carla',
			display_name: 'Carla',
			email: 'carla@example.org',
			role: 'admin',
			language: 'de',
		})
		expect(wrapper.get('[data-test="add-result"]').text()).toContain('Invitation sent')
		expect(listUsers).toHaveBeenCalledTimes(2)

		createUser.mockResolvedValue(account({ id: 'u4', username: 'dino', invited: false }))
		await wrapper.get('[data-test="add-username"]').setValue('dino')
		await wrapper.get('[data-test="user-add-form"]').trigger('submit')
		await flushPromises()
		expect(createUser).toHaveBeenLastCalledWith(expect.objectContaining({ username: 'dino', email: null }))
		expect(wrapper.get('[data-test="add-result"]').text()).toContain('No email: set the password')
	})

	it('shows the backend detail when the server refuses', async () => {
		const { ApiError } = await import('../../frontend/src/api')
		createUser.mockRejectedValue(new ApiError(409, 'That username is taken'))
		const wrapper = mountWithI18n(UsersCard)
		await flushPromises()
		await wrapper.get('[data-test="add-username"]').setValue('anna')
		await wrapper.get('[data-test="user-add-form"]').trigger('submit')
		await flushPromises()
		expect(wrapper.get('[data-test="card-error"]').text()).toBe('That username is taken')
	})

	it('switches role, disables, resends and deletes after confirming', async () => {
		updateUser.mockResolvedValue(account())
		inviteUser.mockResolvedValue({ ok: true, mail: true })
		deleteUser.mockResolvedValue(undefined)
		const wrapper = mountWithI18n(UsersCard)
		await flushPromises()
		const row = () => wrapper.get('[data-test="user-anna"]')
		await row().get('[data-test="user-role"]').trigger('click')
		expect(updateUser).toHaveBeenLastCalledWith('u1', { role: 'organizer' })
		await flushPromises()
		await row().get('[data-test="user-disable"]').trigger('click')
		expect(updateUser).toHaveBeenLastCalledWith('u1', { disabled: true })
		await flushPromises()
		await row().get('[data-test="user-invite"]').trigger('click')
		expect(inviteUser).toHaveBeenCalledWith('u1')
		await flushPromises()
		expect(wrapper.find('[data-test="user-bruno"] [data-test="user-invite"]').exists()).toBe(false)

		await wrapper.get('[data-test="user-bruno"] [data-test="user-delete"]').trigger('click')
		expect(deleteUser).not.toHaveBeenCalled()
		const confirm = wrapper.findAll('[role="dialog"] button').find((b) => b.text() === 'Delete')
		await confirm!.trigger('click')
		await flushPromises()
		expect(deleteUser).toHaveBeenCalledWith('u2')
	})
})

describe('Settings > Organisation', () => {
	async function organisation() {
		getProviders.mockResolvedValue(summary())
		voskModels.mockResolvedValue(catalog())
		const wrapper = mountWithI18n(SettingsView)
		await flushPromises()
		const tab = wrapper.findAll('[role="tab"]').find((b) => b.text().includes(catalogue.tabs.organisation))
		await tab!.trigger('click')
		await flushPromises()
		return wrapper
	}

	it('has no accounts card in Nextcloud mode', async () => {
		auth.config = { ...auth.config!, mode: 'nextcloud' }
		const wrapper = await organisation()
		expect(wrapper.find('[data-test="card-org"]').exists()).toBe(true)
		expect(wrapper.find('[data-test="card-users"]').exists()).toBe(false)
		expect(listUsers).not.toHaveBeenCalled()
		wrapper.unmount()
	})

	it('has the accounts card in standalone mode', async () => {
		const wrapper = await organisation()
		expect(wrapper.find('[data-test="card-users"]').exists()).toBe(true)
		wrapper.unmount()
	})
})
