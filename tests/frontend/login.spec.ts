// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Standalone mode: the login view, the set-password landing, and the app after sign-in. */
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AuthGate from '../../frontend/src/components/auth/AuthGate.vue'
import { auth } from '../../frontend/src/auth'
import { ApiError } from '../../frontend/src/api'
import { mountWithI18n } from './support/mount'

const authConfig = vi.fn()
const me = vi.fn()
const login = vi.fn()
const setPassword = vi.fn()
const requestReset = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: {
		authConfig: (...a: unknown[]) => authConfig(...a),
		me: (...a: unknown[]) => me(...a),
		login: (...a: unknown[]) => login(...a),
		setPassword: (...a: unknown[]) => setPassword(...a),
		requestReset: (...a: unknown[]) => requestReset(...a),
		listAssemblies: async () => [],
		adminPing: async () => ({}),
		updateMe: async () => ({}),
		logout: async () => undefined,
	},
	ApiError: class extends Error {
		status: number
		constructor(status: number, message: string) {
			super(message)
			this.status = status
		}
	},
	setUnauthorizedHandler: vi.fn(),
	BASE: '',
}))

const CONFIG = {
	mode: 'standalone',
	version: '0.9.0-test',
	login: { password: true, oidc: false },
	mail: true,
	languages: ['en', 'it', 'de', 'fr', 'es'],
}
const ACCOUNT = {
	id: 'u1',
	username: 'anna',
	display_name: 'Anna Rossi',
	email: null,
	email_verified: false,
	role: 'admin',
	language: 'it',
	has_password: true,
	oidc: false,
	disabled: false,
	created_at: null,
	last_login_at: null,
	mode: 'standalone',
}

beforeEach(() => {
	vi.clearAllMocks()
	auth.config = null
	auth.account = null
	authConfig.mockResolvedValue(CONFIG)
	history.replaceState(null, '', '/')
})
afterEach(() => history.replaceState(null, '', '/'))

describe('standalone sign-in', () => {
	it('shows the login view when nobody is signed in', async () => {
		me.mockRejectedValue(new ApiError(401, 'Sign in to continue'))
		const wrapper = mountWithI18n(AuthGate)
		await flushPromises()
		expect(wrapper.find('[data-test="login-view"]').exists()).toBe(true)
		expect(wrapper.find('[data-test="account-menu"]').exists()).toBe(false)
	})

	it('shows the app after a successful login and follows the account language', async () => {
		me.mockRejectedValue(new ApiError(401, 'Sign in to continue'))
		login.mockResolvedValue(ACCOUNT)
		const wrapper = mountWithI18n(AuthGate)
		await flushPromises()
		await wrapper.get('#cz-login-username').setValue('anna')
		await wrapper.get('#cz-login-password').setValue('correct horse battery')
		await wrapper.get('form').trigger('submit')
		await flushPromises()
		expect(login).toHaveBeenCalledWith({ username: 'anna', password: 'correct horse battery' })
		expect(wrapper.find('[data-test="login-view"]').exists()).toBe(false)
		expect(wrapper.get('[data-test="account-name"]').text()).toBe('Anna Rossi')
		expect(document.documentElement.lang).toBe('it')
	})

	it('shows the backend detail for a wrong password', async () => {
		me.mockRejectedValue(new ApiError(401, 'Sign in to continue'))
		login.mockRejectedValue(new ApiError(401, 'Wrong username or password'))
		const wrapper = mountWithI18n(AuthGate)
		await flushPromises()
		await wrapper.get('#cz-login-username').setValue('anna')
		await wrapper.get('#cz-login-password').setValue('nope')
		await wrapper.get('form').trigger('submit')
		await flushPromises()
		expect(wrapper.get('[data-test="login-error"]').text()).toBe('Wrong username or password')
		expect(wrapper.find('[data-test="login-view"]').exists()).toBe(true)
	})

	it('always says a link is on its way, and says so when mail is off', async () => {
		me.mockRejectedValue(new ApiError(401, 'x'))
		requestReset.mockResolvedValue({ ok: true })
		const wrapper = mountWithI18n(AuthGate)
		await flushPromises()
		await wrapper.get('[data-test="login-forgot"]').trigger('click')
		await wrapper.get('#cz-login-email').setValue('anna@example.org')
		await wrapper.get('form').trigger('submit')
		await flushPromises()
		expect(requestReset).toHaveBeenCalledWith('anna@example.org')
		expect(wrapper.get('[data-test="reset-sent"]').text()).toContain('If that address has an account')

		authConfig.mockResolvedValue({ ...CONFIG, mail: false })
		const noMail = mountWithI18n(AuthGate)
		await flushPromises()
		await noMail.get('[data-test="login-forgot"]').trigger('click')
		expect(noMail.get('[data-test="reset-by-admin"]').text()).toContain('administrator')
	})

	it('picks the set-password page from ?set-password= and signs in afterwards', async () => {
		history.replaceState(null, '', '/?set-password=tok-1234567890&x=1')
		setPassword.mockResolvedValue(ACCOUNT)
		const wrapper = mountWithI18n(AuthGate)
		await flushPromises()
		expect(me).not.toHaveBeenCalled()
		expect(wrapper.find('[data-test="set-password-view"]').exists()).toBe(true)

		await wrapper.get('#cz-new-password').setValue('short')
		expect(wrapper.get('[data-test="set-password-submit"]').attributes('disabled')).toBeDefined()
		await wrapper.get('#cz-new-password').setValue('a long enough password')
		await wrapper.get('#cz-new-password2').setValue('a long enough password')
		await wrapper.get('form').trigger('submit')
		await flushPromises()
		expect(setPassword).toHaveBeenCalledWith({ token: 'tok-1234567890', password: 'a long enough password' })
		expect(location.search).toBe('?x=1')
		expect(wrapper.find('[data-test="set-password-view"]').exists()).toBe(false)
		expect(wrapper.find('[data-test="account-menu"]').exists()).toBe(true)
	})

	it('goes straight to the app in Nextcloud mode', async () => {
		authConfig.mockResolvedValue({ ...CONFIG, mode: 'nextcloud' })
		const wrapper = mountWithI18n(AuthGate)
		await flushPromises()
		expect(me).not.toHaveBeenCalled()
		expect(wrapper.find('[data-test="login-view"]').exists()).toBe(false)
		expect(wrapper.find('[data-test="account-menu"]').exists()).toBe(false)
	})
})
