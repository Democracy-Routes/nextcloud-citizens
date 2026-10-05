// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The organizer's messages to this table, as they ride the status poll.
 *
 * Every screen that polls `/status` hands the payload to `ingest`; the newest
 * unseen message becomes `current`, the server is told it was shown (the
 * receipt behind "delivered 9/10" on the Live tab), and the banner decides
 * how long to stay. Nothing here touches capture.
 */
import { ref } from 'vue'
import { recorderApi, type PhoneMessage, type RecorderStatus } from './api'

export function useTableMessages(token: string) {
	const current = ref<PhoneMessage | null>(null)
	let newestSeen = 0

	function ingest(status: Pick<RecorderStatus, 'messages'>): void {
		const fresh = (status.messages ?? []).filter((m) => m.id > newestSeen)
		if (!fresh.length) return
		const newest = fresh[fresh.length - 1]
		newestSeen = newest.id
		current.value = newest
		if (newest.sound) {
			try {
				navigator.vibrate?.(200)
			} catch {
				/* not every phone, not every context */
			}
		}
		// the receipt; a failure is harmless — the poll hands it over again
		void recorderApi.messageSeen(token, newest.id).catch(() => undefined)
	}

	function dismiss(): void {
		current.value = null
	}

	return { current, ingest, dismiss }
}
