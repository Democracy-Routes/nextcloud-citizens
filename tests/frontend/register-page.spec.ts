// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Registration on a person's own phone (0.7): the table's code says which
 * event and table, the person reads the same notice and fills the same form,
 * and keeps a page that shows their consent and, once published, the report.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ParticipantPage from '../../frontend/src/recorder/components/ParticipantPage.vue'
import RegisterPage from '../../frontend/src/recorder/components/RegisterPage.vue'
import { mountWithI18n } from './support/mount'

const registerNotice = vi.fn()
const registerSelf = vi.fn()
const participantStatus = vi.fn()

vi.mock('../../frontend/src/recorder/api', () => ({
	recorderApi: {
		registerNotice: (...args: unknown[]) => registerNotice(...args),
		registerSelf: (...args: unknown[]) => registerSelf(...args),
		participantStatus: (...args: unknown[]) => participantStatus(...args),
		participantReport: vi.fn().mockResolvedValue({ assembly: { name: 'Bologna', participants: 1, tables: 1 }, rounds: [] }),
	},
	RecorderApiError: class extends Error {},
}))

const NOTICE = {
	version: '2026-10', language: 'en', hash: 'b'.repeat(64),
	paragraphs: ['Comune is recording this discussion and is responsible for the data.'],
	mode: 'required', participants: [],
	assembly: { id: 'a1', name: 'Bologna', language: 'en', recording_mode: 'orchestrated' },
	table_number: 7, color_key: 'blue',
}

beforeEach(() => {
	registerNotice.mockReset()
	registerSelf.mockReset()
	participantStatus.mockReset()
})

describe('RegisterPage', () => {
	it('shows the code\'s table and notice, registers, and hands over the page token', async () => {
		registerNotice.mockResolvedValue(NOTICE)
		registerSelf.mockResolvedValue({
			participant_token: 'ptok', participant: { id: 'p', label: 'P001', name: 'Giulia' },
			consent: { method: 'SELF_PHONE', recording: true }, table_number: 7, color_key: 'blue',
		})
		const wrapper = mountWithI18n(RegisterPage, { props: { token: 'code' } })
		await flushPromises()
		expect(registerNotice).toHaveBeenCalledWith('code')
		expect(wrapper.text()).toContain('Register at Table 7')
		expect(wrapper.find('[data-test="notice"]').text()).toContain('responsible for the data')
		await wrapper.find('[data-test="register"]').trigger('click')
		await wrapper.find('[data-test="name"]').setValue('Giulia')
		await wrapper.find('[data-test="read"]').setValue(true)
		await wrapper.find('[data-test="recording"]').setValue(true)
		expect(wrapper.find('[data-test="refuse"]').text()).toBe('I do not consent')
		await wrapper.find('[data-test="confirm"]').trigger('click')
		await flushPromises()
		expect(registerSelf).toHaveBeenCalledWith('code', expect.objectContaining({
			name: 'Giulia', notice_hash: 'b'.repeat(64), recording_consent: true,
		}))
		expect(wrapper.emitted('registered')?.[0]).toEqual(['ptok'])
	})

	it('says when a code no longer works', async () => {
		registerNotice.mockRejectedValue(new Error('HTTP 401'))
		const wrapper = mountWithI18n(RegisterPage, { props: { token: 'dead' } })
		await flushPromises()
		expect(wrapper.text()).toContain('This code no longer works')
		expect(wrapper.find('[data-test="register"]').exists()).toBe(false)
	})
})

describe('ParticipantPage', () => {
	it('shows where the person is registered, their consent, and the report once out', async () => {
		participantStatus.mockResolvedValue({
			assembly: { id: 'a1', name: 'Bologna', language: 'en', recording_mode: 'orchestrated' },
			participant: { label: 'P001', name: 'Giulia' }, table_number: 7, color_key: 'blue',
			consent: { recording: true, transcription: true, analysis: false, publication: false, confirmed_at: 'now' },
			report_available: false, contact: 'privacy@example.org', controller: 'Comune',
		})
		const wrapper = mountWithI18n(ParticipantPage, { props: { token: 'ptok' } })
		await flushPromises()
		expect(wrapper.text()).toContain('Hello, Giulia')
		expect(wrapper.text()).toContain('You are registered at Table 7.')
		const ticks = wrapper.findAll('[data-test="consent"] li')
		expect(ticks.map((li) => li.classes().includes('rc-yes'))).toEqual([true, true, false, false])
		expect(wrapper.text()).toContain('contact privacy@example.org')
		expect(wrapper.text()).toContain('The report will appear here when the organizer publishes it.')
		expect(wrapper.find('[data-test="report"]').exists()).toBe(false)

		// once published: the same report the table phones read
		participantStatus.mockResolvedValue({
			...(await participantStatus.mock.results[0].value), report_available: true,
		})
		const later = mountWithI18n(ParticipantPage, { props: { token: 'ptok' } })
		await flushPromises()
		expect(later.text()).toContain('The report has been published.')
		await later.find('[data-test="report"]').trigger('click')
		await flushPromises()
		expect(later.text()).toContain('Bologna')
		expect(later.find('[data-test="report"]').exists()).toBe(false)
	})
})
