// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
import { reactive } from 'vue'

export interface ToastItem {
	id: number
	text: string
	tone: 'success' | 'error'
}

let nextId = 1

export const toasts = reactive<ToastItem[]>([])

/** A confirmation can go; a failure has to be readable.
 *
 * Everything used to vanish after 3.5 seconds, which is not long enough to
 * read an error, work out what it means and act on it — and the container had
 * pointer-events: none, so it could not be held open or dismissed either. */
export const SUCCESS_MS = 3_500
export const ERROR_MS = 10_000

export function dismissToast(id: number): void {
	const index = toasts.findIndex((item) => item.id === id)
	if (index !== -1) toasts.splice(index, 1)
}

export function toast(text: string, tone: 'success' | 'error' = 'success'): number {
	const item: ToastItem = { id: nextId++, text, tone }
	toasts.push(item)
	setTimeout(() => dismissToast(item.id), tone === 'error' ? ERROR_MS : SUCCESS_MS)
	return item.id
}
