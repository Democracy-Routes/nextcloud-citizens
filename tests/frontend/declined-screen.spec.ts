// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * What a phone shows once its person declines the recording notice (0.8).
 * Nothing here calls the server — denying is purely a local choice.
 */
import { describe, expect, it } from 'vitest'
import DeclinedScreen from '../../frontend/src/recorder/components/DeclinedScreen.vue'
import { mountWithI18n } from './support/mount'

describe('the declined screen', () => {
	it('says recording is off on this phone, and offers to read the notice again or scan a fresh code', async () => {
		const wrapper = mountWithI18n(DeclinedScreen)
		expect(wrapper.find('h1').text()).toBe('No recording on this phone.')
		expect(wrapper.text()).toContain('You can still take part in the discussion.')

		await wrapper.find('[data-test="read-again"]').trigger('click')
		expect(wrapper.emitted('read-again')).toBeTruthy()

		await wrapper.find('[data-test="scan-again"]').trigger('click')
		expect(wrapper.emitted('scan-again')).toBeTruthy()
	})
})
