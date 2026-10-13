// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * R31: a phone running in the ordinary browser tab survives switching apps
 * worse than one added to the home screen — so a table should be told, once,
 * never on a phone that is already installed or on a desktop/tablet session.
 */
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ArmedScreen from '../../frontend/src/recorder/components/ArmedScreen.vue'
import { mountWithI18n } from './support/mount'

const status = vi.fn()
const heartbeat = vi.fn().mockResolvedValue(undefined)

vi.mock('../../frontend/src/recorder/api', () => ({
	recorderApi: {
		status: (...args: unknown[]) => status(...args),
		heartbeat: (...args: unknown[]) => heartbeat(...args),
	},
	RecorderApiError: class extends Error {},
}))

const SESSION = {
	session_token: 'tok',
	table_number: 3,
	assembly: { id: 'a1', name: 'Bologna', language: 'en', recording_mode: 'orchestrated' },
	rounds: [],
}

const IPHONE_UA =
	'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
const DESKTOP_UA =
	'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

function setUserAgent(ua: string) {
	Object.defineProperty(window.navigator, 'userAgent', { value: ua, configurable: true })
}

function setIosStandalone(value: boolean | undefined) {
	Object.defineProperty(window.navigator, 'standalone', { value, configurable: true })
}

beforeEach(() => {
	status.mockReset().mockResolvedValue({ rounds: [], report_available: false })
	localStorage.clear()
	setUserAgent(IPHONE_UA)
	setIosStandalone(undefined)
})

afterEach(() => {
	setUserAgent(DESKTOP_UA)
	setIosStandalone(undefined)
})

describe('the add-to-home-screen hint', () => {
	it('shows on a phone browser that is not standalone', async () => {
		const wrapper = mountWithI18n(ArmedScreen, { props: { session: SESSION } })
		await flushPromises()

		const hint = wrapper.find('[data-test="a2hs-hint"]')
		expect(hint.exists()).toBe(true)
		expect(hint.text()).toContain('add this page to your home screen')
	})

	it('goes away once dismissed, and stays away', async () => {
		const wrapper = mountWithI18n(ArmedScreen, { props: { session: SESSION } })
		await flushPromises()

		await wrapper.find('[data-test="a2hs-hint"] button').trigger('click')
		expect(wrapper.find('[data-test="a2hs-hint"]').exists()).toBe(false)

		// a fresh mount on the same device must not show it again
		const again = mountWithI18n(ArmedScreen, { props: { session: SESSION } })
		await flushPromises()
		expect(again.find('[data-test="a2hs-hint"]').exists()).toBe(false)
	})

	it('never shows once the page is already running standalone', async () => {
		setIosStandalone(true)
		const wrapper = mountWithI18n(ArmedScreen, { props: { session: SESSION } })
		await flushPromises()

		expect(wrapper.find('[data-test="a2hs-hint"]').exists()).toBe(false)
	})

	it('never shows on a desktop session', async () => {
		setUserAgent(DESKTOP_UA)
		const wrapper = mountWithI18n(ArmedScreen, { props: { session: SESSION } })
		await flushPromises()

		expect(wrapper.find('[data-test="a2hs-hint"]').exists()).toBe(false)
	})
})
