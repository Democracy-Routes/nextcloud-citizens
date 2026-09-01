// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Make a dialog behave like one.
 *
 * CzConfirm declared aria-modal="true" and did none of what that promises:
 * Tab walked straight out into the page behind the mask, Escape did nothing,
 * nothing was focused when it opened, and focus was not returned afterwards.
 * For a keyboard or screen-reader user the dialog was an announcement they
 * could not reach — in front of buttons that delete an assembly.
 */
import { onBeforeUnmount, onMounted, ref, type Ref } from 'vue'

const FOCUSABLE = [
	'a[href]',
	'button:not([disabled])',
	'input:not([disabled])',
	'select:not([disabled])',
	'textarea:not([disabled])',
	'[tabindex]:not([tabindex="-1"])',
].join(',')

export function useFocusTrap(
	container: Ref<HTMLElement | null>,
	onEscape: () => void,
	options: { initial?: 'first' | 'last' } = {},
): void {
	// where focus was before the dialog opened, so it can be given back
	const previous = ref<HTMLElement | null>(null)

	function focusable(): HTMLElement[] {
		if (!container.value) return []
		return Array.from(container.value.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
			(element) => element.offsetParent !== null || element === document.activeElement,
		)
	}

	function onKeydown(event: KeyboardEvent): void {
		if (event.key === 'Escape') {
			event.preventDefault()
			onEscape()
			return
		}
		if (event.key !== 'Tab') return
		const elements = focusable()
		if (elements.length === 0) return
		const first = elements[0]
		const last = elements[elements.length - 1]
		const active = document.activeElement as HTMLElement | null
		if (event.shiftKey && (active === first || !container.value?.contains(active))) {
			event.preventDefault()
			last.focus()
		} else if (!event.shiftKey && active === last) {
			event.preventDefault()
			first.focus()
		}
	}

	onMounted(() => {
		previous.value = document.activeElement as HTMLElement | null
		const elements = focusable()
		// destructive dialogs focus Cancel, so a stray Enter does nothing
		const target = options.initial === 'last' ? elements[elements.length - 1] : elements[0]
		target?.focus()
		document.addEventListener('keydown', onKeydown, true)
	})

	onBeforeUnmount(() => {
		document.removeEventListener('keydown', onKeydown, true)
		previous.value?.focus?.()
	})
}
