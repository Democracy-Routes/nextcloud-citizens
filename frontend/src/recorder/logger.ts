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

export function initLogger(sessionToken: string): void {
	token = sessionToken
	if (!shipTimer) {
		shipTimer = window.setInterval(() => void ship(), SHIP_INTERVAL_MS)
	}
	window.addEventListener('error', (event) => {
		clientLog('error', 'js_error', { message: String(event.message).slice(0, 300) })
	})
	window.addEventListener('unhandledrejection', (event) => {
		clientLog('error', 'unhandled_rejection', { reason: String(event.reason).slice(0, 300) })
	})
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
