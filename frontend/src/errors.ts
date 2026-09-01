// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Turning a failed request into something a facilitator can act on.
 *
 * Every component used to do `err instanceof Error ? err.message : String(err)`
 * and put the result in a banner. Since api.ts falls back to the literal
 * string `HTTP ${status}` when a response carries no detail, the organizer's
 * error message during a live event was frequently the words "HTTP 500" — no
 * cause, no next step, nothing to tell them whether to retry or fetch a laptop.
 *
 * The server's own 4xx `detail` strings are written for humans and are passed
 * through unchanged. It is the ones that are not that need translating.
 */
import { ApiError } from './api'
import { t } from './i18n'

export type ErrorKind =
	| 'network'
	| 'permission'
	| 'notfound'
	| 'conflict'
	| 'server'
	| 'unknown'

export interface UiError {
	/** One sentence, for the person looking at the screen. */
	message: string
	kind: ErrorKind
	/** The raw text, kept for a details disclosure — never the headline. */
	detail: string
	/** Whether trying the same thing again could plausibly work. */
	retryable: boolean
}

function rawDetail(error: unknown): string {
	if (error instanceof Error) return error.message
	return String(error)
}

export function describeError(error: unknown): UiError {
	const detail = rawDetail(error)

	// fetch itself failed: no response, no status
	if (!(error instanceof ApiError)) {
		return {
			message: t('error.network'),
			kind: 'network',
			detail,
			retryable: true,
		}
	}

	if (error.status === 401 || error.status === 403) {
		return { message: t('error.permission'), kind: 'permission', detail, retryable: false }
	}
	if (error.status === 404) {
		return { message: t('error.notFound'), kind: 'notfound', detail, retryable: false }
	}
	if (error.status === 409) {
		// 409s are deliberate, specific and written for a person to read
		return { message: detail, kind: 'conflict', detail, retryable: false }
	}
	if (error.status === 413) {
		return { message: t('error.tooLarge'), kind: 'conflict', detail, retryable: false }
	}
	if (error.status === 429) {
		return { message: t('error.busy'), kind: 'server', detail, retryable: true }
	}
	if (error.status >= 500) {
		return { message: t('error.server'), kind: 'server', detail, retryable: true }
	}
	// other 4xx: the server's own wording is better than anything generic,
	// unless it is the bare "HTTP nnn" placeholder from api.ts
	const placeholder = /^HTTP \d+$/.test(detail)
	return {
		message: placeholder ? t('error.unknown') : detail,
		kind: 'unknown',
		detail,
		retryable: false,
	}
}
