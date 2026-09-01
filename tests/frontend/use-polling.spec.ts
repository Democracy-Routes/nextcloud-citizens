// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Refreshing a live view, and knowing when it last worked.
 *
 * Every hand-rolled poll in this codebase kept ticking in a background tab and
 * had no idea whether what was on screen was current. A failed poll left the
 * previous result rendered with nothing to say so, which is how the Live tab
 * could show "8/8 tables connected" from several minutes earlier with the
 * countdown beside it still running.
 */
import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { usePolling, type Polling } from '../../frontend/src/composables/usePolling'

function mountPolling(poll: () => Promise<unknown>, options = { intervalMs: 1000 }) {
	let polling!: Polling
	const wrapper = mount(
		defineComponent({
			setup() {
				polling = usePolling(poll, options)
				return () => null
			},
		}),
	)
	return { wrapper, polling: () => polling }
}

beforeEach(() => {
	vi.useFakeTimers()
	Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
})

afterEach(() => {
	vi.useRealTimers()
	vi.restoreAllMocks()
})

describe('usePolling', () => {
	it('polls immediately and then on the interval', async () => {
		const poll = vi.fn().mockResolvedValue(undefined)
		mountPolling(poll)
		await vi.advanceTimersByTimeAsync(0)
		expect(poll).toHaveBeenCalledTimes(1)

		await vi.advanceTimersByTimeAsync(3000)
		expect(poll).toHaveBeenCalledTimes(4)
	})

	it('does not stack calls behind a slow response', async () => {
		let release!: () => void
		const poll = vi.fn(
			() => new Promise<void>((resolve) => { release = resolve }),
		)
		mountPolling(poll)
		await vi.advanceTimersByTimeAsync(0)

		await vi.advanceTimersByTimeAsync(5000)
		expect(poll).toHaveBeenCalledTimes(1)

		release()
	})

	it('stops when the component goes away', async () => {
		const poll = vi.fn().mockResolvedValue(undefined)
		const { wrapper } = mountPolling(poll)
		await vi.advanceTimersByTimeAsync(0)
		wrapper.unmount()

		await vi.advanceTimersByTimeAsync(5000)
		expect(poll).toHaveBeenCalledTimes(1)
	})

	it('records the time of the last SUCCESSFUL poll, not the last attempt', async () => {
		let ok = true
		const poll = vi.fn(async () => {
			if (!ok) throw new Error('unreachable')
		})
		const { polling } = mountPolling(poll)
		await vi.advanceTimersByTimeAsync(0)
		const good = polling().lastSuccessAt.value

		ok = false
		await vi.advanceTimersByTimeAsync(3000)

		// the stamp must keep pointing at data that was real
		expect(polling().lastSuccessAt.value).toBe(good)
		expect(polling().consecutiveFailures.value).toBeGreaterThan(0)
	})

	it('clears the failure count once it recovers', async () => {
		let ok = false
		const poll = vi.fn(async () => {
			if (!ok) throw new Error('unreachable')
		})
		const { polling } = mountPolling(poll)
		await vi.advanceTimersByTimeAsync(1500)
		expect(polling().consecutiveFailures.value).toBeGreaterThan(0)

		ok = true
		await vi.advanceTimersByTimeAsync(1500)

		expect(polling().consecutiveFailures.value).toBe(0)
	})

	it('pauses in a background tab and refreshes on return', async () => {
		const poll = vi.fn().mockResolvedValue(undefined)
		mountPolling(poll)
		await vi.advanceTimersByTimeAsync(0)
		expect(poll).toHaveBeenCalledTimes(1)

		Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true })
		await vi.advanceTimersByTimeAsync(5000)
		expect(poll).toHaveBeenCalledTimes(1)

		Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
		document.dispatchEvent(new Event('visibilitychange'))
		await vi.advanceTimersByTimeAsync(0)
		expect(poll).toHaveBeenCalledTimes(2)
	})

	it('keeps polling in the background when told to', async () => {
		const poll = vi.fn().mockResolvedValue(undefined)
		mountPolling(poll, { intervalMs: 1000, pauseWhenHidden: false })
		await vi.advanceTimersByTimeAsync(0)
		Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true })

		await vi.advanceTimersByTimeAsync(2000)

		expect(poll.mock.calls.length).toBeGreaterThan(1)
	})

	it('can be paused and resumed by the caller', async () => {
		const poll = vi.fn().mockResolvedValue(undefined)
		const { polling } = mountPolling(poll)
		await vi.advanceTimersByTimeAsync(0)
		polling().pause()

		await vi.advanceTimersByTimeAsync(5000)
		expect(poll).toHaveBeenCalledTimes(1)

		polling().resume()
		await vi.advanceTimersByTimeAsync(0)
		expect(poll).toHaveBeenCalledTimes(2)
	})
})
