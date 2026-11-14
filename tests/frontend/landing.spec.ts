// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/** The standalone landing page: description, links, and the embedded login card. */
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

	it('shows the hero title and the login card', () => {
		expect(wrapper.find('[data-test="landing-title"]').text()).toBe('Citizens')
		expect(wrapper.find('[data-test="login-view"]').exists()).toBe(true)
	})

	it('describes four steps and two tools', () => {
		expect(wrapper.findAll('[data-test="landing-step"]')).toHaveLength(4)
		expect(wrapper.find('[data-test="landing-tool-citizens"]').exists()).toBe(true)
		expect(wrapper.find('[data-test="landing-tool-polis"]').exists()).toBe(true)
	})

	it('links to the real addresses, in a new tab', () => {
		const anchors = wrapper.findAll('a[target="_blank"]')
		const hrefs = anchors.map((a) => a.attributes('href'))
		for (const key of ['DEMOCRACY_ROUTES_URL', 'CITIZENS_REPO_URL', 'POLIS_REPO_URL', 'POLIS_INSTANCE_URL', 'LICENSE_URL'] as const) {
			expect(hrefs).toContain(LANDING_LINKS[key])
		}
		for (const a of anchors) expect(a.attributes('rel')).toContain('noopener')
		expect(wrapper.text()).toContain(LANDING_LINKS.POWERED_BY)
	})
})
