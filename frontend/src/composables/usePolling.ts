// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Keeping a view up to date, and honest about when it last was.
 *
 * Two things every hand-rolled poll in this codebase got wrong. They kept
 * ticking while the tab was in the background, and they had no idea whether
 * the data on screen was current — a failed poll left the previous result
 * rendered with no indication, so "8/8 tables connected" could be minutes old
 * while the countdown beside it carried on.
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'

export interface Polling {
	/** Refresh now (a manual button, or regaining focus). */
	refresh: () => Promise<void>
	pause: () => void
	resume: () => void
	lastSuccessAt: import('vue').Ref<Date | null>
	consecutiveFailures: import('vue').Ref<number>
	paused: import('vue').Ref<boolean>
}

export function usePolling(
	poll: () => Promise<unknown>,
	options: { intervalMs: number; pauseWhenHidden?: boolean } = { intervalMs: 15_000 },
): Polling {
	const lastSuccessAt = ref<Date | null>(null)
	const consecutiveFailures = ref(0)
	const paused = ref(false)
	let timer = 0
	let inFlight = false

	async function refresh(): Promise<void> {
		// a slow response must not let calls stack up behind it
		if (inFlight) return
		inFlight = true
		try {
			await poll()
			lastSuccessAt.value = new Date()
			consecutiveFailures.value = 0
		} catch {
			// the caller renders its own error; this only tracks freshness
			consecutiveFailures.value += 1
		} finally {
			inFlight = false
		}
	}

	function tick(): void {
		if (paused.value) return
		if (options.pauseWhenHidden !== false && document.visibilityState !== 'visible') return
		void refresh()
	}

	function onVisibilityChange(): void {
		// coming back to a stale screen is the moment freshness matters most
		if (document.visibilityState === 'visible' && !paused.value) void refresh()
	}

	onMounted(() => {
		void refresh()
		timer = window.setInterval(tick, options.intervalMs)
		document.addEventListener('visibilitychange', onVisibilityChange)
		window.addEventListener('online', onVisibilityChange)
	})

	onBeforeUnmount(() => {
		window.clearInterval(timer)
		document.removeEventListener('visibilitychange', onVisibilityChange)
		window.removeEventListener('online', onVisibilityChange)
	})

	return {
		refresh,
		pause: () => {
			paused.value = true
		},
		resume: () => {
			paused.value = false
			void refresh()
		},
		lastSuccessAt,
		consecutiveFailures,
		paused,
	}
}
