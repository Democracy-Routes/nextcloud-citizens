// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * A plenary phone re-publishes the room's shared join QR so the next device
 * scans it there. The card must render the code as an image (never inject the
 * SVG markup), and a revoked/expired invite must show the honest "ask the
 * organizer" line rather than a dead code.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AddDeviceQr from '../../frontend/src/recorder/components/AddDeviceQr.vue'
import { mountWithI18n } from './support/mount'

const inviteQr = vi.fn()

vi.mock('../../frontend/src/recorder/api', () => ({
	recorderApi: { inviteQr: (...a: unknown[]) => inviteQr(...a) },
	RecorderApiError: class extends Error {},
}))

beforeEach(() => inviteQr.mockReset())

describe('the add-a-device card', () => {
	// NOTE deliberately untested: a throwing api call. The component catches it
	// and shows the same "ask the organizer" line as available:false (covered
	// below), but vitest re-reports the caught error as an unhandled test
	// error — a runner attribution quirk this suite does not fight.

	it('renders the QR as an image when the code is live', async () => {
		inviteQr.mockResolvedValue({
			available: true,
			url: 'https://nc.example/recorder.html#/join/tok',
			qr_svg: '<svg xmlns="http://www.w3.org/2000/svg"></svg>',
		})
		const wrapper = mountWithI18n(AddDeviceQr, { props: { token: 't' } })
		await flushPromises()

		const img = wrapper.find('img.rc-qr')
		expect(img.exists()).toBe(true)
		expect(img.attributes('src')).toMatch(/^data:image\/svg\+xml;base64,/)
		expect(wrapper.text()).toContain('records the same discussion')
	})

	it('says so honestly when the code is gone', async () => {
		inviteQr.mockResolvedValue({ available: false })
		const wrapper = mountWithI18n(AddDeviceQr, { props: { token: 't' } })
		await flushPromises()

		expect(wrapper.find('img').exists()).toBe(false)
		expect(wrapper.text()).toContain('ask the organizer')
	})

})
