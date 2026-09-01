// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * A phone must lose its session ONLY when the server has actually rejected it.
 *
 * Every status failure used to clear the stored session, so a single bad
 * response on venue WiFi during a reload disconnected the table for good — the
 * facilitator had to be found and a new QR code scanned, mid-round.
 */
import { describe, expect, it } from 'vitest'
import { RecorderApiError } from '../../frontend/src/recorder/api'
import {
	decideOnStatusFailure,
	isGoneError,
	isTransientError,
} from '../../frontend/src/recorder/errors'

describe('what a failed status check means for a stored session', () => {
	it('keeps the session when the network is the problem', () => {
		expect(decideOnStatusFailure(new TypeError('Failed to fetch'))).toBe('retry')
	})

	it('keeps the session when the server is having a moment', () => {
		for (const status of [500, 502, 503, 504]) {
			expect(decideOnStatusFailure(new RecorderApiError(status, 'boom'))).toBe('retry')
		}
	})

	it('keeps the session when the server is rate limiting a burst of tables', () => {
		expect(decideOnStatusFailure(new RecorderApiError(429, 'slow down'))).toBe('retry')
	})

	it('clears the session only when the server definitively rejects it', () => {
		for (const status of [401, 403, 404, 410]) {
			expect(decideOnStatusFailure(new RecorderApiError(status, 'gone'))).toBe('clear')
		}
	})
})

describe('the predicates the engine shares with the boot path', () => {
	it('treats a plain network failure as transient, not gone', () => {
		const err = new TypeError('Failed to fetch')
		expect(isGoneError(err)).toBe(false)
		expect(isTransientError(err)).toBe(true)
	})

	it('treats a revoked session as gone, not transient', () => {
		const err = new RecorderApiError(401, 'unauthorized')
		expect(isGoneError(err)).toBe(true)
		expect(isTransientError(err)).toBe(false)
	})

	it('does not consider a 400 worth retrying', () => {
		expect(isTransientError(new RecorderApiError(400, 'bad request'))).toBe(false)
	})
})
