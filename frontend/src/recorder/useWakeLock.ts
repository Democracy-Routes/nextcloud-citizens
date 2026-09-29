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
 *
 * The `active` condition is watched, not read once. The recording screen
 * passes "the engine is recording", which is false at the instant the screen
 * mounts (the recording starts in the screen's own onMounted, after this
 * composable's): a one-shot read skipped the request, and the lock was only
 * taken on the next visibilitychange — after the screen had gone dark and
 * somebody had woken the phone by hand. Every outcome is written to the
 * device log, because a silently refused lock looks exactly like a phone
 * whose owner set auto-lock to 30 seconds.
 */
import { onBeforeUnmount, onMounted, ref, toValue, watch, type MaybeRefOrGetter, type Ref } from 'vue'
import { clientLog } from './logger'

/** Whether the mounted screen currently holds the lock; null where the
 * browser has no Wake Lock API at all. One recorder screen is mounted at a
 * time, so a single flag is accurate — the heartbeat reports it. */
export const wakeLockHeld = ref<boolean | null>(null)

const RETRY_MS = 5_000
let unsupportedLogged = false

export function isWakeLockSupported(): boolean {
	return typeof navigator !== 'undefined' && !!navigator.wakeLock
}

export function useWakeLock(
	active: MaybeRefOrGetter<boolean> = () => true,
): { held: Ref<boolean>; supported: boolean } {
	const supported = isWakeLockSupported()
	const held = ref(false)
	let sentinel: WakeLockSentinel | null = null
	let acquiring = false
	let retryTimer = 0

	function setHeld(value: boolean): void {
		held.value = value
		wakeLockHeld.value = supported ? value : null
	}

	async function acquire(): Promise<void> {
		if (!toValue(active) || document.visibilityState !== 'visible') return
		if (acquiring || sentinel) return
		if (!supported) {
			if (!unsupportedLogged) {
				unsupportedLogged = true
				clientLog('warn', 'wake_lock_unsupported')
			}
			setHeld(false)
			return
		}
		acquiring = true
		try {
			const lock = await navigator.wakeLock.request('screen')
			sentinel = lock
			lock.addEventListener('release', onRelease)
			setHeld(true)
			clientLog('info', 'wake_lock_acquired')
		} catch (error) {
			setHeld(false)
			const named = error as { name?: string; message?: string } | null
			clientLog('warn', 'wake_lock_failed', {
				name: named?.name ?? '',
				message: String(named?.message ?? error).slice(0, 160),
			})
		} finally {
			acquiring = false
		}
	}

	/** The browser let go of the lock: on hide (expected — visibilitychange
	 * asks again), or on its own (battery saver, a system dialog). One
	 * bounded retry while visible; never a loop against a refusing browser. */
	function onRelease(): void {
		sentinel = null
		setHeld(false)
		const visible = document.visibilityState === 'visible'
		clientLog('warn', 'wake_lock_released', { visible })
		if (visible && toValue(active)) {
			window.clearTimeout(retryTimer)
			retryTimer = window.setTimeout(() => {
				retryTimer = 0
				void acquire()
			}, RETRY_MS)
		}
	}

	async function release(): Promise<void> {
		window.clearTimeout(retryTimer)
		retryTimer = 0
		const lock = sentinel
		sentinel = null
		if (!lock) return
		lock.removeEventListener('release', onRelease)
		try {
			await lock.release()
		} catch {
			/* already gone */
		}
		setHeld(false)
	}

	function onVisibilityChange(): void {
		if (document.visibilityState === 'visible') void acquire()
	}

	watch(
		() => toValue(active),
		(on) => {
			if (on) void acquire()
			else void release()
		},
	)

	onMounted(() => {
		void acquire()
		document.addEventListener('visibilitychange', onVisibilityChange)
	})

	onBeforeUnmount(() => {
		document.removeEventListener('visibilitychange', onVisibilityChange)
		void release()
	})

	return { held, supported }
}
