// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/** The standalone sign-in page: the login card, and the way back to the project site. */
import { describe, expect, it, vi } from 'vitest'
import LandingView from '../../frontend/src/components/auth/LandingView.vue'
import { LANDING_LINKS } from '../../frontend/src/landing-links'
import { mountWithI18n } from './support/mount'

vi.mock('../../frontend/src/api', () => ({
	api: {},
	ApiError: class extends Error {},
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

describe('LandingView', () => {
	const wrapper = mountWithI18n(LandingView, { props: { config: CONFIG } })

	it('shows the title, the claim and the login card', () => {
		expect(wrapper.find('[data-test="landing-title"]').text()).toBe('Citizens')
		expect(wrapper.text()).toContain('from the table to the report')
		expect(wrapper.find('[data-test="login-view"]').exists()).toBe(true)
	})

	it('links back to the project site and carries the brand line', () => {
		const back = wrapper.find('[data-test="landing-back"]')
		expect(back.attributes('href')).toBe(LANDING_LINKS.DEMOCRACY_ROUTES_URL)
		expect(back.text()).toContain('Return to democracyroutes.com')
		expect(wrapper.text()).toContain(LANDING_LINKS.POWERED_BY)
	})

	it('describes nothing else: the project description lives on democracyroutes.com', () => {
		expect(wrapper.findAll('section').length).toBe(0)
		expect(wrapper.text()).not.toContain('GitHub')
	})
})
