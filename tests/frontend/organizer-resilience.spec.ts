// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The organizer UI must not lie when the API is unreachable.
 *
 * Five components had no catch on their initial load, so a failure produced an
 * unhandled rejection and a confident empty state. The worst was the sidebar:
 * it said "No assemblies yet" and the main pane invited the facilitator to
 * create their first assembly — during an event, with assemblies that existed.
 * Acting on that invitation creates a duplicate.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAsyncAction } from '../../frontend/src/composables/useAsyncAction'
import { useAsyncData } from '../../frontend/src/composables/useAsyncData'

describe('useAsyncData', () => {
	it('surfaces a failure instead of leaving the data empty and silent', async () => {
		const { data, error, loading } = useAsyncData(async () => {
			throw new TypeError('Failed to fetch')
		})
		await flushPromises()

		expect(data.value).toBeNull()
		expect(error.value?.kind).toBe('network')
		expect(loading.value).toBe(false)
	})

	it('records when the data was last known to be good', async () => {
		const { loadedAt, reload } = useAsyncData(async () => ['a'])
		await flushPromises()
		const first = loadedAt.value

		expect(first).toBeInstanceOf(Date)

		await reload()
		expect(loadedAt.value!.getTime()).toBeGreaterThanOrEqual(first!.getTime())
	})

	it('keeps the last good data when a refresh fails', async () => {
		let attempt = 0
		const { data, error, reload } = useAsyncData(async () => {
			attempt += 1
			if (attempt > 1) throw new TypeError('Failed to fetch')
			return ['first']
		})
		await flushPromises()

		await reload()

		// blanking the table mid-event would be worse than showing it stale;
		// the freshness stamp is what tells the facilitator which it is
		expect(data.value).toEqual(['first'])
		expect(error.value).not.toBeNull()
	})

	it('does not blank the screen while refreshing existing data', async () => {
		const { loading, refreshing, reload } = useAsyncData(async () => ['x'])
		await flushPromises()
		expect(loading.value).toBe(false)

		const pending = reload()
		expect(loading.value).toBe(false)
		expect(refreshing.value).toBe(true)
		await pending
	})

	it('collapses concurrent loads into one request', async () => {
		const load = vi.fn().mockResolvedValue(['x'])
		const { reload } = useAsyncData(load, { immediate: false })

		await Promise.all([reload(), reload(), reload()])

		expect(load).toHaveBeenCalledTimes(1)
	})
})

describe('useAsyncAction', () => {
	let action: ReturnType<typeof vi.fn>

	beforeEach(() => {
		action = vi.fn().mockResolvedValue(undefined)
	})

	it('ignores the second half of a double-click', async () => {
		const { run } = useAsyncAction()

		// exactly what a facilitator does with a trackpad under time pressure
		await Promise.all([run(action), run(action)])

		expect(action).toHaveBeenCalledTimes(1)
	})

	it('reports whether the action actually succeeded', async () => {
		const { run } = useAsyncAction()

		expect(await run(action)).toBe(true)
		expect(await run(async () => Promise.reject(new TypeError('boom')))).toBe(false)
	})

	it('describes the failure rather than exposing the raw exception', async () => {
		const { run, error } = useAsyncAction()

		await run(async () => Promise.reject(new TypeError('Failed to fetch')))

		expect(error.value?.message).not.toContain('Failed to fetch')
		expect(error.value?.detail).toContain('Failed to fetch')
	})

	it('clears a previous failure when the retry works', async () => {
		const { run, error } = useAsyncAction()
		await run(async () => Promise.reject(new TypeError('boom')))
		expect(error.value).not.toBeNull()

		await run(action)

		expect(error.value).toBeNull()
	})

	it('releases the guard even when the action throws', async () => {
		const { run, busy } = useAsyncAction()

		await run(async () => Promise.reject(new TypeError('boom')))

		expect(busy.value).toBe(false)
		expect(await run(action)).toBe(true)
	})
})
