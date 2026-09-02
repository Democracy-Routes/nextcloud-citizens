// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Reading the battery must never break the heartbeat.
 *
 * The heartbeat is how a facilitator knows a table is alive. Battery is a
 * nice-to-have riding along with it, so every way the browser can refuse —
 * no API at all, a permissions policy, a rejected promise — has to end in
 * "unknown" rather than an exception that costs the heartbeat.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../frontend/src/recorder/api', () => ({
	recorderApi: {},
	RecorderApiError: class extends Error {},
}))
vi.mock('../../frontend/src/recorder/idb', () => ({ idb: {} }))
vi.mock('../../frontend/src/recorder/logger', () => ({ clientLog: vi.fn() }))
vi.mock('../../frontend/src/recorder/sha', () => ({ sha256Hex: vi.fn() }))

const { readBatteryLevel } = await import('../../frontend/src/recorder/engine')

afterEach(() => {
	Reflect.deleteProperty(navigator, 'getBattery')
})

function withGetBattery(impl: unknown) {
	Object.defineProperty(navigator, 'getBattery', { value: impl, configurable: true })
}

describe('readBatteryLevel', () => {
	it('reports the level where the browser provides one', async () => {
		withGetBattery(async () => ({ level: 0.42 }))
		expect(await readBatteryLevel()).toBe(0.42)
	})

	it('returns undefined on Safari and Firefox, which do not implement it', async () => {
		expect(await readBatteryLevel()).toBeUndefined()
	})

	it('returns undefined rather than throwing when the call is blocked', async () => {
		// a permissions policy, or an insecure context
		withGetBattery(async () => {
			throw new Error('blocked by permissions policy')
		})
		expect(await readBatteryLevel()).toBeUndefined()
	})

	it('does not invent a level from a malformed response', async () => {
		withGetBattery(async () => ({ level: 'quite full' }))
		expect(await readBatteryLevel()).toBeUndefined()
	})
})
