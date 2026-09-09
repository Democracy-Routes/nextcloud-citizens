// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The consent screen is the first thing every citizen sees, and it long
 * referenced button classes that never existed (rc-btn--primary / rc-btn--block),
 * so its "Agree" call to action rendered as the neutral grey button. This pins
 * the real accent class onto it.
 */
import { describe, expect, it } from 'vitest'
import ConsentScreen from '../../frontend/src/recorder/components/ConsentScreen.vue'
import { mountWithI18n } from './support/mount'

describe('the consent call to action', () => {
	it('renders Agree as the primary (accent) button, and emits accept', async () => {
		const wrapper = mountWithI18n(ConsentScreen, {
			props: { handling: { stt_provider: 'mistral', stt_hosted: true }, tableNumber: 3 },
		})

		const agree = wrapper.find('button.rc-primary')
		expect(agree.exists()).toBe(true)
		// the dead class names are gone
		expect(wrapper.html()).not.toContain('rc-btn--primary')
		expect(wrapper.html()).not.toContain('rc-btn--block')

		await agree.trigger('click')
		expect(wrapper.emitted('accept')).toBeTruthy()
	})
})
