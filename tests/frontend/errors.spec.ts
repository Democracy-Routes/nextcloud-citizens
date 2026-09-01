// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * "HTTP 500" is not an error message.
 *
 * api.ts falls back to the literal string `HTTP ${status}` when a response
 * carries no detail, and every organizer component piped that straight into a
 * banner. During a live event the facilitator's entire diagnosis was those two
 * words: no cause, no indication of whether retrying would help.
 */
import { describe, expect, it } from 'vitest'
import { ApiError } from '../../frontend/src/api'
import { describeError } from '../../frontend/src/errors'
import { i18n } from '../../frontend/src/i18n'

describe('describeError', () => {
	it('never surfaces the bare HTTP placeholder as the message', () => {
		const described = describeError(new ApiError(500, 'HTTP 500'))

		expect(described.message).not.toBe('HTTP 500')
		expect(described.message.split(' ').length).toBeGreaterThan(3)
		expect(described.detail).toBe('HTTP 500')
	})

	it('says a server fault is worth retrying and a permission problem is not', () => {
		expect(describeError(new ApiError(503, 'HTTP 503')).retryable).toBe(true)
		expect(describeError(new ApiError(403, 'Forbidden')).retryable).toBe(false)
	})

	it('recognises a dropped connection as a connection problem', () => {
		const described = describeError(new TypeError('Failed to fetch'))

		expect(described.kind).toBe('network')
		expect(described.retryable).toBe(true)
	})

	it("passes a 409's own wording through, because it was written for a person", () => {
		const detail = 'This recording is being assembled right now. Wait for it to finish.'

		expect(describeError(new ApiError(409, detail)).message).toBe(detail)
	})

	it('prefers the server wording over a generic sentence for other 4xx', () => {
		const detail = 'A round must have at least one table'

		expect(describeError(new ApiError(400, detail)).message).toBe(detail)
	})

	it('translates the generic messages', () => {
		i18n.global.locale.value = 'it'
		const italian = describeError(new ApiError(500, 'HTTP 500')).message
		i18n.global.locale.value = 'en'
		const english = describeError(new ApiError(500, 'HTTP 500')).message

		expect(italian).not.toBe(english)
		expect(italian.length).toBeGreaterThan(3)
	})

	it('keeps the raw text available for whoever has to debug it', () => {
		expect(describeError(new ApiError(500, 'Traceback: boom')).detail).toBe('Traceback: boom')
	})
})
