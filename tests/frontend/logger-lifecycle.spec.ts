// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The device log must say what the phone did to the page, and what the phone
 * was.
 *
 * After the September 2026 rehearsals the browser family of a failing phone
 * had to be inferred from the wording of its error messages, and a recording
 * that simply stopped could not be told apart from a page that had been sent
 * to the background. And every join re-registered the global error listeners,
 * so a reconnected phone logged each error twice.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

const append = vi.fn().mockResolvedValue(undefined)
const take = vi.fn().mockResolvedValue({ entries: [], lastKey: 0 })
vi.mock('../../frontend/src/recorder/idb', () => ({
	logsDb: {
		append: (...a: unknown[]) => append(...a),
		take: (...a: unknown[]) => take(...a),
		deleteUpTo: vi.fn().mockResolvedValue(undefined),
	},
}))

const shipLogs = vi.fn().mockResolvedValue({ accepted: 0 })
vi.mock('../../frontend/src/recorder/api', () => ({
	recorderApi: { shipLogs: (...a: unknown[]) => shipLogs(...a) },
}))

import { initLogger } from '../../frontend/src/recorder/logger'

function events(): string[] {
	return append.mock.calls.map((call) => (call[0] as { event: string }).event)
}

beforeEach(() => {
	append.mockClear()
	take.mockClear()
	shipLogs.mockClear()
})

describe('initLogger', () => {
	it('describes the device once, with its user agent', () => {
		initLogger('tok')
		initLogger('tok-again')

		const described = append.mock.calls.filter((c) => (c[0] as { event: string }).event === 'device_info')
		expect(described).toHaveLength(1)
		const data = (described[0][0] as { data: { ua: string } }).data
		expect(data.ua).toBe(navigator.userAgent)
	})

	it('registers the error listeners once, however often a session is entered', () => {
		initLogger('tok')
		initLogger('tok-again')
		append.mockClear()

		window.dispatchEvent(new ErrorEvent('error', { message: 'boom' }))

		expect(events().filter((e) => e === 'js_error')).toHaveLength(1)
	})

	it('logs the page going to the background and ships the log at once', async () => {
		initLogger('tok')
		append.mockClear()

		Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true })
		document.dispatchEvent(new Event('visibilitychange'))
		await Promise.resolve()

		expect(events()).toEqual(['page_hidden'])
		expect(take).toHaveBeenCalled()

		Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
		document.dispatchEvent(new Event('visibilitychange'))
		expect(events()).toEqual(['page_hidden', 'page_shown'])
	})

	it('logs the page being torn down or frozen', () => {
		initLogger('tok')
		append.mockClear()

		window.dispatchEvent(new Event('pagehide'))
		document.dispatchEvent(new Event('freeze'))

		expect(events()).toEqual(['page_hide', 'page_freeze'])
	})
})
