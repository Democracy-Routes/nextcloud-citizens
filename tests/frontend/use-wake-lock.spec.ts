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
 *
 * Then the recording screen itself: it asked for the lock "while recording",
 * a condition that is false at the instant the screen mounts (recording
 * starts a tick later) and was read exactly once. So the lock was never
 * requested there, the screen went dark at the phone's timeout, and it only
 * came back — for good — once somebody woke the phone by hand and the
 * visibilitychange path asked again. The condition is watched now.
 */
import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, nextTick, reactive } from 'vue'

const clientLog = vi.fn()
vi.mock('../../frontend/src/recorder/logger', () => ({
	clientLog: (...args: unknown[]) => clientLog(...args),
	ship: vi.fn().mockResolvedValue(undefined),
}))

const { useWakeLock, wakeLockHeld } = await import('../../frontend/src/recorder/useWakeLock')

const release = vi.fn().mockResolvedValue(undefined)
const listeners: Record<string, () => void> = {}
const sentinel = {
	release,
	addEventListener: vi.fn((name: string, handler: () => void) => {
		listeners[name] = handler
	}),
	removeEventListener: vi.fn(),
}
const request = vi.fn().mockResolvedValue(sentinel)

beforeEach(() => {
	vi.useFakeTimers()
	request.mockClear()
	release.mockClear()
	clientLog.mockClear()
	sentinel.addEventListener.mockClear()
	Object.defineProperty(navigator, 'wakeLock', { value: { request }, configurable: true })
	Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
})

afterEach(() => {
	vi.useRealTimers()
	vi.restoreAllMocks()
})

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

const settled = async () => {
	await vi.advanceTimersByTimeAsync(0)
	await nextTick()
}

const logged = (event: string) => clientLog.mock.calls.filter((call) => call[1] === event)

describe('useWakeLock', () => {
	it('holds the screen awake as soon as the component appears', async () => {
		mountWith()
		await settled()
		expect(request).toHaveBeenCalledWith('screen')
		expect(logged('wake_lock_acquired')).toHaveLength(1)
		expect(wakeLockHeld.value).toBe(true)
	})

	it('asks for the lock the moment the condition turns true after mount', async () => {
		// the recording screen: idle at mount, recording a tick later
		const engine = reactive({ phase: 'idle' })
		mountWith(() => engine.phase === 'recording')
		await settled()
		expect(request).not.toHaveBeenCalled()

		engine.phase = 'recording'
		await settled()

		expect(request).toHaveBeenCalledWith('screen')
	})

	it('lets go when the condition turns false again', async () => {
		const engine = reactive({ phase: 'recording' })
		mountWith(() => engine.phase === 'recording')
		await settled()
		expect(request).toHaveBeenCalledTimes(1)

		engine.phase = 'failed'
		await settled()

		expect(release).toHaveBeenCalled()
		expect(wakeLockHeld.value).toBe(false)
	})

	it('re-acquires when the page becomes visible again', async () => {
		mountWith()
		await settled()
		request.mockClear()

		// the browser drops the lock whenever the page is hidden, so coming
		// back has to ask again — requesting once at mount is not enough
		listeners.release?.()
		document.dispatchEvent(new Event('visibilitychange'))
		await settled()

		expect(request).toHaveBeenCalledWith('screen')
	})

	it('asks once more, after a pause, when the browser releases it on its own', async () => {
		mountWith()
		await settled()
		request.mockClear()

		// battery saver, a system dialog: released while still on screen
		listeners.release?.()
		await settled()
		expect(logged('wake_lock_released')).toHaveLength(1)
		expect(wakeLockHeld.value).toBe(false)
		expect(request).not.toHaveBeenCalled()

		await vi.advanceTimersByTimeAsync(5_000)
		expect(request).toHaveBeenCalledTimes(1)
	})

	it('writes a refusal to the device log instead of swallowing it', async () => {
		const error = Object.assign(new Error('not allowed'), { name: 'NotAllowedError' })
		request.mockRejectedValueOnce(error)

		mountWith()
		await settled()

		expect(logged('wake_lock_failed')).toHaveLength(1)
		expect(logged('wake_lock_failed')[0][2]).toMatchObject({ name: 'NotAllowedError' })
		expect(wakeLockHeld.value).toBe(false)
	})

	it('releases the lock when the screen is left', async () => {
		const wrapper = mountWith()
		await settled()
		wrapper.unmount()
		await settled()
		expect(release).toHaveBeenCalled()
		// our own release is not an event worth a warning
		expect(logged('wake_lock_released')).toHaveLength(0)
	})

	it('does not ask while the caller says there is nothing to stay awake for', async () => {
		mountWith(() => false)
		await settled()
		expect(request).not.toHaveBeenCalled()
	})

	it('survives a browser with no wake lock support, and says so once', async () => {
		Object.defineProperty(navigator, 'wakeLock', { value: undefined, configurable: true })
		expect(() => mountWith()).not.toThrow()
		await settled()
		mountWith()
		await settled()

		expect(logged('wake_lock_unsupported')).toHaveLength(1)
		expect(wakeLockHeld.value).toBeNull()
	})
})
