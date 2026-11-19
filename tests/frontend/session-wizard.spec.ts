// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Create a session is one step: question, optional objective, duration,
 * tables, mode. It asks for no assembly and sends exactly what the server's
 * SessionCreate accepts. "Add another session" turns it into a multi-session
 * event, which goes to createAssembly with one round per session.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SessionWizard from '../../frontend/src/components/SessionWizard.vue'
import { mountWithI18n } from './support/mount'

const createSession = vi.fn()
const createAssembly = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: {
		createSession: (...a: unknown[]) => createSession(...a),
		createAssembly: (...a: unknown[]) => createAssembly(...a),
	},
	ApiError: class extends Error {
		status = 0
	},
	BASE: '',
}))

// a block body: a returned mock would be run as the teardown hook
beforeEach(() => {
	createSession.mockReset()
	createAssembly.mockReset().mockResolvedValue({ id: 'a1', invites: [{ table_number: 1, url: 'u', qr_svg: '<svg/>' }] })
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

	it('allows a duration of 0 — no planned time — and does not block starting', async () => {
		const wrapper = mountWithI18n(SessionWizard)
		await wrapper.find('#cz-session-question').setValue('Q')
		await wrapper.find('#cz-session-duration').setValue(0)

		expect(wrapper.text()).toContain('No planned time')
		expect(submitButton(wrapper).attributes('disabled')).toBeUndefined()

		createSession.mockResolvedValue({
			session_id: 'r', container_id: 'c', question: 'Q', objective: null,
			recording_mode: 'orchestrated', table_count: 1, invites: [],
		})
		await submitButton(wrapper).trigger('click')
		await flushPromises()
		expect(createSession.mock.calls[0][0]).toMatchObject({ duration_minutes: 0 })
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

	describe('adding a second session', () => {
		async function twoSessions() {
			const wrapper = mountWithI18n(SessionWizard)
			await wrapper.find('#cz-session-question').setValue('Q1')
			await wrapper.find('[data-test="wizard-add-session"]').trigger('click')
			return wrapper
		}
		function createButton(wrapper: ReturnType<typeof mountWithI18n>) {
			return wrapper.findAll('button').find((b) => b.text().includes('Create the multi-session event'))!
		}

		it('asks for a name and sends createAssembly with two rounds', async () => {
			const wrapper = await twoSessions()
			expect(wrapper.find('h2').text()).toBe('Create a multi-session event')
			expect(wrapper.find('[data-test="wizard-multi"]').exists()).toBe(true)

			// the second session needs a question, and the event a name
			expect(createButton(wrapper).attributes('disabled')).toBeDefined()
			await wrapper.find('#cz-session-question-1').setValue('  Q2  ')
			expect(createButton(wrapper).attributes('disabled')).toBeDefined()
			await wrapper.find('#cz-event-name').setValue('  Bologna Mobility  ')
			await wrapper.find('#cz-session-title').setValue('Opening')
			await wrapper.find('#cz-session-objective').setValue('Three proposals')
			await wrapper.find('#cz-session-duration-1').setValue(0)
			await wrapper.find('#cz-session-tables').setValue(5)
			expect(createButton(wrapper).attributes('disabled')).toBeUndefined()

			await createButton(wrapper).trigger('click')
			await flushPromises()

			expect(createSession).not.toHaveBeenCalled()
			expect(createAssembly).toHaveBeenCalledWith({
				name: 'Bologna Mobility',
				description: '',
				language: 'en',
				recording_mode: 'orchestrated',
				expected_participants: 50,
				default_table_count: 5,
				analysis_instructions: '',
				rounds: [
					{ title: 'Opening', question: 'Q1', objective: 'Three proposals', duration_minutes: 30 },
					{ title: 'Session 2', question: 'Q2', objective: undefined, duration_minutes: 0 },
				],
				participant_consent: 'required',
				zero_retention: false,
				audio_retention_days: null,
			})
			expect(wrapper.emitted('created')?.[0]).toEqual([
				'a1', [{ table_number: 1, url: 'u', qr_svg: '<svg/>' }],
			])
		})

		it('removing the second session goes back to createSession', async () => {
			const wrapper = await twoSessions()
			await wrapper.find('[data-test="wizard-remove-session"]').trigger('click')

			expect(wrapper.find('[data-test="wizard-multi"]').exists()).toBe(false)
			expect(wrapper.find('h2').text()).toBe('Create a session')
			createSession.mockResolvedValue({
				session_id: 'r', container_id: 'c', question: 'Q1', objective: null,
				recording_mode: 'orchestrated', table_count: 1, invites: [],
			})
			await submitButton(wrapper).trigger('click')
			await flushPromises()
			expect(createAssembly).not.toHaveBeenCalled()
			expect(createSession.mock.calls[0][0]).toMatchObject({ question: 'Q1' })
		})

		describe('retention choice', () => {
			async function ready() {
				const wrapper = await twoSessions()
				await wrapper.find('#cz-session-question-1').setValue('Q2')
				await wrapper.find('#cz-event-name').setValue('Bologna Mobility')
				return wrapper
			}

			it('defaults to the instance default, unselected audio_retention_days', async () => {
				const wrapper = await ready()
				await createButton(wrapper).trigger('click')
				await flushPromises()
				expect(createAssembly.mock.calls[0][0]).toMatchObject({ audio_retention_days: null, zero_retention: false })
			})

			it('sends the chosen number of days', async () => {
				const wrapper = await ready()
				const radios = wrapper.findAll('[data-test="retention"] input[type="radio"]')
				await radios[1].setValue() // "days"
				await wrapper.find('[data-test="retention"] input[type="number"]').setValue(45)
				await createButton(wrapper).trigger('click')
				await flushPromises()
				expect(createAssembly.mock.calls[0][0]).toMatchObject({ audio_retention_days: 45, zero_retention: false })
			})

			it('sends zero retention and leaves audio_retention_days out of it', async () => {
				const wrapper = await ready()
				const radios = wrapper.findAll('[data-test="retention"] input[type="radio"]')
				await radios[2].setValue() // "zero"
				await createButton(wrapper).trigger('click')
				await flushPromises()
				const sent = createAssembly.mock.calls[0][0]
				expect(sent.zero_retention).toBe(true)
				expect(sent.audio_retention_days).toBeUndefined()
			})
		})
	})
})
