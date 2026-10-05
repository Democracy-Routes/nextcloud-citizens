// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Start a Session is one step: question, optional objective, duration,
 * tables, mode. It asks for no assembly and sends exactly what the server's
 * SessionCreate accepts.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SessionWizard from '../../frontend/src/components/SessionWizard.vue'
import { mountWithI18n } from './support/mount'

const createSession = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: { createSession: (...a: unknown[]) => createSession(...a) },
	ApiError: class extends Error {
		status = 0
	},
	BASE: '',
}))

// a block body: a returned mock would be run as the teardown hook
beforeEach(() => {
	createSession.mockReset()
})

function submitButton(wrapper: ReturnType<typeof mountWithI18n>) {
	return wrapper.findAll('button').find((b) => b.text().includes('Start Session'))!
}

describe('the session wizard', () => {
	it('will not start without a question', async () => {
		const wrapper = mountWithI18n(SessionWizard)
		expect(submitButton(wrapper).attributes('disabled')).toBeDefined()

		await wrapper.find('#cz-session-question').setValue('How should local mobility improve?')
		expect(submitButton(wrapper).attributes('disabled')).toBeUndefined()
	})

	it('sends question, objective, duration, tables and mode, then hands over the QR codes', async () => {
		createSession.mockResolvedValue({
			session_id: 'r-1', container_id: 'c-1', question: 'Q', objective: 'O',
			recording_mode: 'independent', table_count: 4,
			invites: [{ table_number: 1, url: 'u', qr_svg: '<svg/>' }],
		})
		const wrapper = mountWithI18n(SessionWizard)

		await wrapper.find('#cz-session-question').setValue('  How should local mobility improve?  ')
		await wrapper.find('#cz-session-objective').setValue('Produce three concrete proposals.')
		await wrapper.find('#cz-session-duration').setValue(20)
		await wrapper.find('#cz-session-tables').setValue(4)
		await wrapper.find('input[value="independent"]').setValue()
		await wrapper.find('#cz-session-language').setValue('it')
		await submitButton(wrapper).trigger('click')
		await flushPromises()

		expect(createSession).toHaveBeenCalledWith({
			question: 'How should local mobility improve?',
			objective: 'Produce three concrete proposals.',
			duration_minutes: 20,
			table_count: 4,
			recording_mode: 'independent',
			language: 'it',
		})
		expect(wrapper.emitted('created')?.[0]).toEqual([
			'c-1', [{ table_number: 1, url: 'u', qr_svg: '<svg/>' }],
		])
	})

	it('sends no objective when none was typed', async () => {
		createSession.mockResolvedValue({
			session_id: 'r-1', container_id: 'c-1', question: 'Q', objective: null,
			recording_mode: 'orchestrated', table_count: 1, invites: [],
		})
		const wrapper = mountWithI18n(SessionWizard)

		await wrapper.find('#cz-session-question').setValue('Q')
		await submitButton(wrapper).trigger('click')
		await flushPromises()

		expect(createSession.mock.calls[0][0]).toMatchObject({ objective: null, table_count: 1 })
	})

	it('one room, many phones means one table', async () => {
		const wrapper = mountWithI18n(SessionWizard)
		await wrapper.find('#cz-session-tables').setValue(6)
		await wrapper.find('input[value="plenary"]').setValue()

		expect(wrapper.find('#cz-session-tables').exists()).toBe(false)
		await wrapper.find('#cz-session-question').setValue('Q')
		createSession.mockResolvedValue({
			session_id: 'r', container_id: 'c', question: 'Q', objective: null,
			recording_mode: 'plenary', table_count: 1, invites: [],
		})
		await submitButton(wrapper).trigger('click')
		await flushPromises()
		expect(createSession.mock.calls[0][0]).toMatchObject({ recording_mode: 'plenary', table_count: 1 })
	})

	it('keeps the form and shows the reason when the server refuses', async () => {
		createSession.mockRejectedValue(new Error('HTTP 503'))
		const wrapper = mountWithI18n(SessionWizard)

		await wrapper.find('#cz-session-question').setValue('Q')
		await submitButton(wrapper).trigger('click')
		await flushPromises()

		expect(wrapper.find('.cz-error').text()).toContain('HTTP 503')
		expect(wrapper.emitted('created')).toBeUndefined()
		expect((wrapper.find('#cz-session-question').element as HTMLTextAreaElement).value).toBe('Q')
	})
})
