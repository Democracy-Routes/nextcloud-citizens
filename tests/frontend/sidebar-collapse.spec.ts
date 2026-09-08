// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The assemblies column collapses on desktop, Calendar-style: a toggle at its
 * edge hides the list, gives the detail view the full width, and the choice
 * is remembered per browser.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../../frontend/src/App.vue'
import { mountWithI18n } from './support/mount'

vi.mock('../../frontend/src/api', () => ({
	api: {
		listAssemblies: vi.fn().mockResolvedValue([]),
		adminPing: vi.fn().mockResolvedValue(undefined),
	},
	ApiError: class extends Error {
		status = 0
	},
	BASE: '',
}))

beforeEach(() => localStorage.clear())

describe('collapsing the assemblies column', () => {
	it('toggles the collapsed class and remembers the choice', async () => {
		const wrapper = mountWithI18n(App)
		await flushPromises()

		const aside = wrapper.find('aside.cz-sidebar')
		const toggle = wrapper.find('.cz-sidebar-toggle')
		expect(toggle.exists()).toBe(true)
		expect(aside.classes()).not.toContain('cz-sidebar--collapsed')

		await toggle.trigger('click')
		expect(aside.classes()).toContain('cz-sidebar--collapsed')
		expect(localStorage.getItem('citizens-sidebar-collapsed')).toBe('1')

		await toggle.trigger('click')
		expect(aside.classes()).not.toContain('cz-sidebar--collapsed')
		expect(localStorage.getItem('citizens-sidebar-collapsed')).toBe('0')
	})

	it('starts collapsed when that was the remembered choice', async () => {
		localStorage.setItem('citizens-sidebar-collapsed', '1')
		const wrapper = mountWithI18n(App)
		await flushPromises()

		expect(wrapper.find('aside.cz-sidebar').classes()).toContain('cz-sidebar--collapsed')
	})

	it('leaves the mobile drawer path alone', async () => {
		// the mobile "Assemblies" button drives cz-sidebar--open, a different
		// mechanism; collapsing must not interfere with it
		const wrapper = mountWithI18n(App)
		await flushPromises()

		await wrapper.find('.cz-mobilebar button').trigger('click')
		expect(wrapper.find('aside.cz-sidebar').classes()).toContain('cz-sidebar--open')
	})
})
