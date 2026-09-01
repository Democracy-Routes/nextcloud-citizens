// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The parts of the UI that only some people could use.
 *
 * A confirm dialog declared aria-modal="true" and did none of what that
 * promises — Tab walked out into the page behind it, Escape did nothing, and
 * nothing was focused when it opened. In front of a button that deletes an
 * assembly. Toasts were the only feedback for several actions and were
 * announced to nobody. Icon-only buttons had a `title` and no accessible name,
 * which touch devices never show and screen readers largely ignore.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it, vi } from 'vitest'
import CzButton from '../../frontend/src/components/ui/CzButton.vue'
import CzConfirm from '../../frontend/src/components/ui/CzConfirm.vue'
import CzTabs from '../../frontend/src/components/ui/CzTabs.vue'
import CzToasts from '../../frontend/src/components/ui/CzToasts.vue'
import { toast, toasts } from '../../frontend/src/components/ui/toast'
import { mountWithI18n } from './support/mount'

const CONFIRM = { title: 'Delete round?', message: 'It goes away.', confirmLabel: 'Delete' }

describe('the confirm dialog', () => {
	it('names itself through the roles it declares', () => {
		const wrapper = mountWithI18n(CzConfirm, { props: CONFIRM, attachTo: document.body })
		const dialog = wrapper.find('[role="dialog"]')

		const labelledBy = dialog.attributes('aria-labelledby')
		const describedBy = dialog.attributes('aria-describedby')

		expect(document.getElementById(labelledBy!)?.textContent).toContain('Delete round?')
		expect(document.getElementById(describedBy!)?.textContent).toContain('It goes away.')
		wrapper.unmount()
	})

	it('puts the keyboard inside itself when it opens', async () => {
		const wrapper = mountWithI18n(CzConfirm, { props: CONFIRM, attachTo: document.body })
		await new Promise((resolve) => setTimeout(resolve, 0))

		expect(wrapper.element.contains(document.activeElement)).toBe(true)
		wrapper.unmount()
	})

	it('cancels on Escape', async () => {
		const wrapper = mountWithI18n(CzConfirm, { props: CONFIRM, attachTo: document.body })

		document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
		await new Promise((resolve) => setTimeout(resolve, 0))

		expect(wrapper.emitted('cancel')).toBeTruthy()
		wrapper.unmount()
	})

	it('gives focus back to whatever opened it', async () => {
		const trigger = document.createElement('button')
		document.body.appendChild(trigger)
		trigger.focus()

		const wrapper = mountWithI18n(CzConfirm, { props: CONFIRM, attachTo: document.body })
		await new Promise((resolve) => setTimeout(resolve, 0))
		wrapper.unmount()
		await new Promise((resolve) => setTimeout(resolve, 0))

		expect(document.activeElement).toBe(trigger)
		trigger.remove()
	})
})

describe('toasts', () => {
	it('are announced, with errors interrupting', async () => {
		toasts.splice(0, toasts.length)
		toast('Saved', 'success')
		toast('Could not save', 'error')
		const wrapper = mountWithI18n(CzToasts)
		await wrapper.vm.$nextTick()

		const rendered = wrapper.findAll('.cz-toast')
		expect(rendered[0].attributes('role')).toBe('status')
		expect(rendered[0].attributes('aria-live')).toBe('polite')
		expect(rendered[1].attributes('role')).toBe('alert')
		expect(rendered[1].attributes('aria-live')).toBe('assertive')
	})

	it('can be dismissed rather than only waited out', async () => {
		toasts.splice(0, toasts.length)
		toast('Something happened')
		const wrapper = mountWithI18n(CzToasts)
		await wrapper.vm.$nextTick()

		await wrapper.find('.cz-toast__close').trigger('click')

		expect(toasts).toHaveLength(0)
	})

	it('leaves an error up long enough to read', () => {
		vi.useFakeTimers()
		toasts.splice(0, toasts.length)
		toast('Something broke', 'error')

		vi.advanceTimersByTime(4000)
		expect(toasts).toHaveLength(1)

		vi.advanceTimersByTime(7000)
		expect(toasts).toHaveLength(0)
		vi.useRealTimers()
	})
})

describe('icon-only buttons', () => {
	it('take their accessible name from the title already given', () => {
		const wrapper = mountWithI18n(CzButton, { props: { icon: 'M0 0', title: 'Delete round' } })

		expect(wrapper.attributes('aria-label')).toBe('Delete round')
	})

	it('do not repeat a name a visible label already gives', () => {
		const wrapper = mountWithI18n(CzButton, {
			props: { icon: 'M0 0', label: 'Delete' },
			slots: { default: 'Delete round' },
		})

		expect(wrapper.attributes('aria-label')).toBeUndefined()
	})
})

describe('tabs', () => {
	const tabs = [
		{ id: 'overview', label: 'Overview' },
		{ id: 'rounds', label: 'Rounds' },
	]

	it('points each tab at the panel it controls', () => {
		const wrapper = mountWithI18n(CzTabs, {
			props: { tabs, modelValue: 'overview', idPrefix: 'a' },
		})

		expect(wrapper.findAll('[role="tab"]')[0].attributes('aria-controls')).toBe('a-panel-overview')
	})

	it('keeps one tab in the tab order, not all of them', () => {
		const wrapper = mountWithI18n(CzTabs, {
			props: { tabs, modelValue: 'overview', idPrefix: 'a' },
		})
		const rendered = wrapper.findAll('[role="tab"]')

		expect(rendered[0].attributes('tabindex')).toBe('0')
		expect(rendered[1].attributes('tabindex')).toBe('-1')
	})

	it('moves between tabs with the arrow keys', async () => {
		const wrapper = mountWithI18n(CzTabs, {
			props: { tabs, modelValue: 'overview', idPrefix: 'a' },
		})

		await wrapper.find('[role="tablist"]').trigger('keydown', { key: 'ArrowRight' })

		expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['rounds'])
	})

	it('wraps around at the end', async () => {
		const wrapper = mountWithI18n(CzTabs, {
			props: { tabs, modelValue: 'rounds', idPrefix: 'a' },
		})

		await wrapper.find('[role="tablist"]').trigger('keydown', { key: 'ArrowRight' })

		expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['overview'])
	})
})

describe('type scale', () => {
	function vueFiles(directory: string): string[] {
		return readdirSync(directory).flatMap((entry) => {
			const path = join(directory, entry)
			if (statSync(path).isDirectory()) return vueFiles(path)
			return path.endsWith('.vue') ? [path] : []
		})
	}

	it('never pins text to a pixel size', () => {
		// a fixed px size ignores the Nextcloud font setting, which is the
		// setting anyone who needs larger text has already found
		const offenders = vueFiles(join(__dirname, '..', '..', 'frontend', 'src'))
			.flatMap((file) => {
				const matches = readFileSync(file, 'utf8').match(/font-size:\s*\d+(\.\d+)?px/g) ?? []
				return matches.map((match) => `${file.split('/').slice(-1)[0]}: ${match}`)
			})

		expect(offenders).toEqual([])
	})
})
