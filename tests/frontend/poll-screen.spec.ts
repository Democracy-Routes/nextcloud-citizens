// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The recorder's poll screen: the Polis voting link as a button, and its QR as
 * an image (never injected markup). Participants' own pages show the link only.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PollScreen from '../../frontend/src/recorder/components/PollScreen.vue'
import { mountWithI18n } from './support/mount'

const pollQr = vi.fn()

vi.mock('../../frontend/src/recorder/api', () => ({
	recorderApi: { pollQr: (...a: unknown[]) => pollQr(...a) },
	RecorderApiError: class extends Error {},
}))

beforeEach(() => pollQr.mockReset())

describe('the poll screen', () => {
	it('renders the link and the QR image', async () => {
		pollQr.mockResolvedValue({ available: true, url: 'https://p.example/abc', qr_svg: '<svg xmlns="http://www.w3.org/2000/svg"/>' })
		const wrapper = mountWithI18n(PollScreen, { props: { token: 't' } })
		await flushPromises()
		expect(pollQr).toHaveBeenCalledWith('t')
		const link = wrapper.find('[data-test="poll-link"]')
		expect(link.attributes('href')).toBe('https://p.example/abc')
		expect(link.attributes('target')).toBe('_blank')
		expect(link.attributes('rel')).toBe('noopener')
		expect(wrapper.text()).toContain('https://p.example/abc')
		expect(wrapper.find('img[data-test="poll-qr"]').attributes('src')).toContain('data:image/svg+xml')
	})

	it('emits back', async () => {
		pollQr.mockResolvedValue({ available: false })
		const wrapper = mountWithI18n(PollScreen, { props: { token: 't' } })
		await flushPromises()
		expect(wrapper.find('[data-test="poll-link"]').exists()).toBe(false)
		await wrapper.find('[data-test="poll-back"]').trigger('click')
		expect(wrapper.emitted('back')).toHaveLength(1)
	})
})
