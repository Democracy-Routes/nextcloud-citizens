// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The QR tab is the one screen used with people waiting at the door.
 *
 * Two things were wrong there. "Regenerate all" invalidated every code already
 * printed and taped to a table and asked nothing first — while the strictly
 * milder "Revoke all" did ask. And the printable sheet opened in a new tab,
 * which a pop-up blocker swallows silently, at the single most time-critical
 * moment of the event.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CzQrImage from '../../frontend/src/components/ui/CzQrImage.vue'
import QrTab from '../../frontend/src/components/QrTab.vue'
import { mountWithI18n } from './support/mount'

const listInvites = vi.fn()
const inviteLinks = vi.fn()
const generateInvites = vi.fn()
const pollQr = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: {
		listInvites: (...a: unknown[]) => listInvites(...a),
		inviteLinks: (...a: unknown[]) => inviteLinks(...a),
		generateInvites: (...a: unknown[]) => generateInvites(...a),
		revokeInvites: vi.fn(),
		pollQr: (...a: unknown[]) => pollQr(...a),
	},
	ApiError: class extends Error {},
	BASE: '',
}))

const ACTIVE_INVITES = [
	{ id: 'i1', table_number: 1, active: true, expires_at: null },
	{ id: 'i2', table_number: 2, active: true, expires_at: null },
]

const ASSEMBLY = { id: 'a1', name: 'Bologna', default_table_count: 2, rounds: [] }

beforeEach(() => {
	listInvites.mockReset().mockResolvedValue(ACTIVE_INVITES)
	inviteLinks.mockReset().mockResolvedValue([])
	generateInvites.mockReset().mockResolvedValue([])
	pollQr.mockReset().mockResolvedValue({ available: false, published: false, url: null, qr_svg: null })
})

describe('regenerating the codes', () => {
	it('asks first, naming how many printed codes stop working', async () => {
		const wrapper = mountWithI18n(QrTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		const regenerate = wrapper
			.findAll('button')
			.find((b) => b.text().includes('Regenerate all'))!
		await regenerate.trigger('click')

		expect(generateInvites).not.toHaveBeenCalled()
		expect(wrapper.text()).toContain('2 codes already printed')
	})

	it('generates without asking when there is nothing to invalidate', async () => {
		listInvites.mockResolvedValue([])
		const wrapper = mountWithI18n(QrTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		const generate = wrapper.findAll('button').find((b) => b.text().includes('Generate codes'))!
		await generate.trigger('click')

		expect(generateInvites).toHaveBeenCalled()
	})
})

describe('rendering a code', () => {
	it('cannot execute script embedded in the SVG', () => {
		const hostile = '<svg xmlns="http://www.w3.org/2000/svg"><script>window.pwned = 1</script></svg>'
		const wrapper = mountWithI18n(CzQrImage, { props: { svg: hostile, label: 'Table 1' } })

		// an <img> cannot run script whatever the document contains
		expect(wrapper.find('script').exists()).toBe(false)
		expect(wrapper.find('img').attributes('src')).toContain('data:image/svg+xml')
	})

	it('labels the code for anyone who cannot see it', () => {
		const wrapper = mountWithI18n(CzQrImage, {
			props: { svg: '<svg/>', label: 'QR code for table 3' },
		})

		expect(wrapper.find('img').attributes('alt')).toBe('QR code for table 3')
	})
})

describe('the Polis poll card', () => {
	it('is hidden when there is no poll', async () => {
		const wrapper = mountWithI18n(QrTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()
		expect(wrapper.find('[data-test="qr-poll"]').exists()).toBe(false)
	})

	it('is hidden when the call fails', async () => {
		pollQr.mockRejectedValue(new Error('boom'))
		const wrapper = mountWithI18n(QrTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()
		expect(wrapper.find('[data-test="qr-poll"]').exists()).toBe(false)
	})

	it('shows the code, the link and whether the phones show it', async () => {
		pollQr.mockResolvedValue({
			available: true, published: false, published_at: null, url: 'https://p.example/abc', qr_svg: '<svg/>',
		})
		const wrapper = mountWithI18n(QrTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()
		const card = wrapper.find('[data-test="qr-poll"]')
		expect(card.exists()).toBe(true)
		expect(card.find('img').attributes('src')).toContain('data:image/svg+xml')
		expect(card.text()).toContain('https://p.example/abc')
		expect(card.text()).toContain('Not yet shown on the phones')
	})

	it('says so once published', async () => {
		pollQr.mockResolvedValue({
			available: true, published: true, published_at: 'x', url: 'https://p.example/abc', qr_svg: '<svg/>',
		})
		const wrapper = mountWithI18n(QrTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()
		expect(wrapper.find('[data-test="qr-poll"]').text()).toContain('Shown on the table phones')
	})
})
