// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/*
 * Client-side diagnostic logger: entries persist to IndexedDB alongside the
 * audio chunks and ship to the server opportunistically (same offline-first
 * pattern). This is the diagnostic trail for phones nobody can debug live.
 */

import { recorderApi } from './api'
import { logsDb } from './idb'

export interface ClientLogEntry {
	ts: number
	level: 'info' | 'warn' | 'error'
	event: string
	data?: Record<string, unknown>
}

const SHIP_INTERVAL_MS = 15_000
const SHIP_BATCH = 100

let token = ''
let shipTimer = 0
let listenersInstalled = false
let deviceDescribed = false

export function initLogger(sessionToken: string): void {
	token = sessionToken
	if (!shipTimer) {
		shipTimer = window.setInterval(() => void ship(), SHIP_INTERVAL_MS)
	}
	// Once per page: this runs on every join and every offline resume, and
	// each call used to add another pair of listeners, so a reconnected phone
	// logged every error twice, then three times.
	if (!listenersInstalled) {
		listenersInstalled = true
		window.addEventListener('error', (event) => {
			clientLog('error', 'js_error', { message: String(event.message).slice(0, 300) })
		})
		window.addEventListener('unhandledrejection', (event) => {
			clientLog('error', 'unhandled_rejection', { reason: String(event.reason).slice(0, 300) })
		})
		installLifecycleLog()
	}
	if (!deviceDescribed) {
		deviceDescribed = true
		describeDevice()
	}
}

/** Which browser this is. Nothing recorded it, so after a rehearsal the
 * browser family of a failing phone was inferred from the wording of its
 * error messages. */
function describeDevice(): void {
	try {
		clientLog('info', 'device_info', {
			ua: String(navigator.userAgent).slice(0, 240),
			standalone: window.matchMedia?.('(display-mode: standalone)').matches ?? false,
			online: navigator.onLine,
		})
	} catch {
		/* a description is a nicety; the log must not depend on it */
	}
}

/** The page going to the background, being frozen, or being torn down.
 *
 * iOS can stop the microphone when the recorder page is hidden, with no
 * error the page can catch. Without these lines the device log showed a
 * recording that simply stopped, and nobody could say whether the phone had
 * been locked, another app opened, or the tab reloaded. Shipping on hide is
 * best-effort: the entry is in IndexedDB either way and goes out on the next
 * visit if the page does not live long enough to send it now.
 */
function installLifecycleLog(): void {
	document.addEventListener('visibilitychange', () => {
		const hidden = document.visibilityState === 'hidden'
		clientLog('warn', hidden ? 'page_hidden' : 'page_shown')
		if (hidden) void ship()
	})
	window.addEventListener('pagehide', (event) => {
		clientLog('warn', 'page_hide', { persisted: (event as PageTransitionEvent).persisted === true })
		void ship()
	})
	window.addEventListener('pageshow', (event) => {
		if ((event as PageTransitionEvent).persisted) clientLog('warn', 'page_restored')
	})
	document.addEventListener('freeze', () => {
		clientLog('warn', 'page_freeze')
		void ship()
	})
	document.addEventListener('resume', () => clientLog('warn', 'page_resume'))
}

export function clientLog(
	level: ClientLogEntry['level'],
	event: string,
	data?: Record<string, unknown>,
): void {
	const entry: ClientLogEntry = { ts: Date.now() / 1000, level, event }
	if (data) entry.data = data
	try {
		logsDb.append(entry).catch(() => undefined)
	} catch {
		// a log line must never take the recorder down with it
	}
}

export async function ship(): Promise<void> {
	if (!token || !navigator.onLine) return
	try {
		const batch = await logsDb.take(SHIP_BATCH)
		if (batch.entries.length === 0) return
		await recorderApi.shipLogs(token, batch.entries)
		await logsDb.deleteUpTo(batch.lastKey)
	} catch {
		/* keep entries; retried on the next interval */
	}
}
