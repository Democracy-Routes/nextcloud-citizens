// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * A phone waiting for the facilitator must not fall asleep.
 *
 * Only the recording screen ever held a wake lock. A table armed and waiting
 * for the round to open therefore let its screen lock, which stops the poll
 * and the heartbeat: the organizer's monitor shows the table as STALE, and the
 * phone never notices the round starting. The table sits there recording
 * nothing until somebody touches the screen.
 */
import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { useWakeLock } from '../../frontend/src/recorder/useWakeLock'

const release = vi.fn().mockResolvedValue(undefined)
const request = vi.fn().mockResolvedValue({ release })

beforeEach(() => {
	request.mockClear()
	release.mockClear()
	Object.defineProperty(navigator, 'wakeLock', { value: { request }, configurable: true })
	Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
})

afterEach(() => vi.restoreAllMocks())

function mountWith(active?: () => boolean) {
	return mount(
		defineComponent({
			setup() {
				useWakeLock(active)
				return () => null
			},
		}),
	)
}

const settled = () => new Promise((resolve) => setTimeout(resolve, 0))

describe('useWakeLock', () => {
	it('holds the screen awake as soon as the component appears', async () => {
		mountWith()
		await settled()
		expect(request).toHaveBeenCalledWith('screen')
	})

	it('re-acquires when the page becomes visible again', async () => {
		mountWith()
		await settled()
		request.mockClear()

		// the browser drops the lock whenever the page is hidden, so coming
		// back has to ask again — requesting once at mount is not enough
		document.dispatchEvent(new Event('visibilitychange'))
		await settled()

		expect(request).toHaveBeenCalledWith('screen')
	})

	it('releases the lock when the screen is left', async () => {
		const wrapper = mountWith()
		await settled()
		wrapper.unmount()
		await settled()
		expect(release).toHaveBeenCalled()
	})

	it('does not ask while the caller says there is nothing to stay awake for', async () => {
		mountWith(() => false)
		await settled()
		expect(request).not.toHaveBeenCalled()
	})

	it('survives a browser with no wake lock support', async () => {
		Object.defineProperty(navigator, 'wakeLock', { value: undefined, configurable: true })
		expect(() => mountWith()).not.toThrow()
		await settled()
	})
})
