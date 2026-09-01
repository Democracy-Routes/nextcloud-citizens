// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Keep the phone's screen awake for as long as it is doing something.
 *
 * A table's phone is unattended for most of an assembly: propped up, nobody
 * touching it. Only the recording screen ever asked for a wake lock, so a
 * phone waiting in ARMED for the facilitator to open the round went to sleep —
 * which stops its polling and its heartbeat, shows the table as STALE on the
 * organizer's monitor, and means it never notices the round starting. The
 * table then sits there recording nothing.
 *
 * The lock is also dropped by the browser whenever the page is hidden, so it
 * has to be re-acquired on visibilitychange rather than requested once.
 */
import { onBeforeUnmount, onMounted } from 'vue'

export function useWakeLock(active: () => boolean = () => true): void {
	let sentinel: WakeLockSentinel | null = null

	async function acquire(): Promise<void> {
		if (!active() || document.visibilityState !== 'visible') return
		try {
			sentinel = (await navigator.wakeLock?.request('screen')) ?? null
		} catch {
			/* unsupported, or refused while backgrounded — the UI tells the
			   table to keep the page open, which is the fallback */
		}
	}

	async function release(): Promise<void> {
		try {
			await sentinel?.release()
		} catch {
			/* already gone */
		}
		sentinel = null
	}

	function onVisibilityChange(): void {
		if (document.visibilityState === 'visible') void acquire()
	}

	onMounted(() => {
		void acquire()
		document.addEventListener('visibilitychange', onVisibilityChange)
	})

	onBeforeUnmount(() => {
		document.removeEventListener('visibilitychange', onVisibilityChange)
		void release()
	})
}
