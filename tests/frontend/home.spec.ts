// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Home is where everyone lands: Record now, Start a Session, Create an
 * Assembly. Nobody is made to configure an assembly to record a discussion,
 * and a standalone Session is listed as a Session, never as an assembly.
 */
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../../frontend/src/App.vue'
import { mountWithI18n } from './support/mount'

const listAssemblies = vi.fn()
const recordNow = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: {
		listAssemblies: (...a: unknown[]) => listAssemblies(...a),
		recordNow: (...a: unknown[]) => recordNow(...a),
		adminPing: vi.fn().mockRejectedValue(Object.assign(new Error('nope'), { status: 403 })),
	},
	ApiError: class extends Error {
		status = 403
	},
	BASE: '',
}))

const session = {
	id: 's-1', kind: 'session', name: 'How should local mobility improve?', status: 'DRAFT',
	recording_mode: 'orchestrated', expected_participants: 0, default_table_count: 3, language: 'en',
}
const assembly = {
	id: 'a-1', kind: 'assembly', name: 'Milan Mobility', status: 'ACTIVE',
	recording_mode: 'orchestrated', expected_participants: 50, default_table_count: 10, language: 'it',
}

beforeEach(() => {
	listAssemblies.mockReset().mockResolvedValue([])
	recordNow.mockReset()
	document.documentElement.lang = 'it-IT'
})

afterEach(() => {
	vi.restoreAllMocks()
})

describe('the home screen', () => {
	it('offers the three ways in, and does not open an assembly by itself', async () => {
		listAssemblies.mockResolvedValue([assembly])
		const wrapper = mountWithI18n(App)
		await flushPromises()

		const names = wrapper.findAll('.cz-home__action-name').map((n) => n.text())
		expect(names).toEqual(['Record now', 'Start a Session', 'Create an Assembly'])
		// the first assembly used to be opened automatically on load
		expect(wrapper.find('.cz-pagehead').exists()).toBe(false)
	})

	it('Record now asks for a Session in the page language and opens the recorder', async () => {
		recordNow.mockResolvedValue({
			session_id: 'r-1', container_id: 'c-1', table_number: 1,
			recorder_url: 'https://cloud.example/recorder.html#/join/tok',
		})
		const open = vi.spyOn(window, 'open').mockReturnValue({} as Window)
		const wrapper = mountWithI18n(App)
		await flushPromises()

		await wrapper.find('.cz-home__action--primary').trigger('click')
		await flushPromises()

		expect(recordNow).toHaveBeenCalledWith({ language: 'it' })
		expect(open).toHaveBeenCalledWith('https://cloud.example/recorder.html#/join/tok', '_blank', 'noopener')
		// nothing to fall back to: the tab opened
		expect(wrapper.find('.cz-home__link').exists()).toBe(false)
	})

	it('shows the recorder link when the browser blocked the new tab', async () => {
		recordNow.mockResolvedValue({
			session_id: 'r-1', container_id: 'c-1', table_number: 1,
			recorder_url: 'https://cloud.example/recorder.html#/join/tok',
		})
		vi.spyOn(window, 'open').mockReturnValue(null)
		const wrapper = mountWithI18n(App)
		await flushPromises()

		await wrapper.find('.cz-home__action--primary').trigger('click')
		await flushPromises()

		const link = wrapper.find('a.cz-home__link')
		expect(link.attributes('href')).toBe('https://cloud.example/recorder.html#/join/tok')
		expect(link.attributes('target')).toBe('_blank')
	})

	it('says so when Record now fails, instead of pretending', async () => {
		recordNow.mockRejectedValue(new Error('HTTP 503'))
		const wrapper = mountWithI18n(App)
		await flushPromises()

		await wrapper.find('.cz-home__action--primary').trigger('click')
		await flushPromises()

		expect(wrapper.find('.cz-error').text()).toContain('HTTP 503')
		expect(wrapper.find('.cz-home__action-name').text()).toBe('Record now')
	})

	it('Start a Session opens the session wizard, Create an Assembly the assembly wizard', async () => {
		const wrapper = mountWithI18n(App)
		await flushPromises()

		await wrapper.findAll('.cz-home__action')[1].trigger('click')
		expect(wrapper.find('h2').text()).toBe('Start a Session')
		expect(wrapper.find('#cz-session-objective').exists()).toBe(true)

		// the sidebar's Home button leads back; the home view is mounted afresh
		await wrapper.find('.cz-sidebar__top button').trigger('click')
		expect(wrapper.find('.cz-home__title').exists()).toBe(true)
		await wrapper.findAll('.cz-home__action')[2].trigger('click')
		expect(wrapper.find('h2').text()).toBe('Create assembly')
	})

	it('lists a standalone Session as a Session under its question, apart from assemblies', async () => {
		listAssemblies.mockResolvedValue([session, assembly])
		const wrapper = mountWithI18n(App)
		await flushPromises()

		const groups = wrapper.findAll('.cz-sidebar__group').map((g) => g.text())
		expect(groups).toEqual(['Sessions', 'Assemblies'])
		const items = wrapper.findAll('.cz-navitem')
		expect(items[0].find('.cz-navitem__name').text()).toBe('How should local mobility improve?')
		expect(items[0].find('.cz-navitem__meta').text()).toBe('Session · 3 tables')
		expect(items[0].text()).not.toContain('participants')
		expect(items[1].find('.cz-navitem__name').text()).toBe('Milan Mobility')
		expect(items[1].find('.cz-navitem__meta').text()).toContain('50 participants')
	})

	it('needs no group heading when there are only assemblies', async () => {
		listAssemblies.mockResolvedValue([assembly])
		const wrapper = mountWithI18n(App)
		await flushPromises()

		expect(wrapper.findAll('.cz-sidebar__group')).toHaveLength(0)
	})
})
