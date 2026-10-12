// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * One person's registration form: the required box (recording, transcription,
 * analysis) and the optional quotations box, ticked by default, each worded by
 * the notice itself; a refusal needs only a name; a change of mind has the
 * name fixed and no refusal.
 */
import { describe, expect, it } from 'vitest'
import ConsentForm from '../../frontend/src/recorder/components/ConsentForm.vue'
import { mountWithI18n } from './support/mount'

const ACCEPT = 'By registering you consent to the recording, its transcription and analysis.'
const QUOTES = 'I also agree to short anonymous quotations from my table in the report.'

describe('the consent form', () => {
	it('has two boxes worded by the notice, the quotations one ticked by default', async () => {
		const wrapper = mountWithI18n(ConsentForm, { props: { acceptance: ACCEPT, acceptanceQuotations: QUOTES } })
		const ticks = wrapper.findAll('.rc-tick')
		expect(ticks.map((tick) => tick.text())).toEqual([ACCEPT, QUOTES])
		expect((wrapper.find('[data-test="accept"]').element as HTMLInputElement).checked).toBe(false)
		expect((wrapper.find('[data-test="quotations"]').element as HTMLInputElement).checked).toBe(true)

		await wrapper.find('[data-test="name"]').setValue('Anna')
		expect(wrapper.find('[data-test="confirm"]').attributes('disabled')).toBeDefined()
		await wrapper.find('[data-test="accept"]').setValue(true)
		await wrapper.find('[data-test="confirm"]').trigger('click')
		expect(wrapper.emitted('confirm')?.[0]).toEqual([{ name: 'Anna', email: '', accepted: true, quotations: true }])
	})

	it('lets a person consent to the processing and decline quotations', async () => {
		const wrapper = mountWithI18n(ConsentForm, { props: { acceptance: ACCEPT, acceptanceQuotations: QUOTES } })
		await wrapper.find('[data-test="name"]').setValue('Bruno')
		await wrapper.find('[data-test="accept"]').setValue(true)
		await wrapper.find('[data-test="quotations"]').setValue(false)
		await wrapper.find('[data-test="confirm"]').trigger('click')
		expect(wrapper.emitted('confirm')?.[0]).toEqual([{ name: 'Bruno', email: '', accepted: true, quotations: false }])
	})

	it('records a change of mind for a named person: no refusal, no email', async () => {
		const wrapper = mountWithI18n(ConsentForm, { props: { acceptance: ACCEPT, fixedName: 'Carla' } })
		const name = wrapper.find('[data-test="name"]').element as HTMLInputElement
		expect(name.value).toBe('Carla')
		expect(name.disabled).toBe(true)
		expect(wrapper.find('[data-test="email"]').exists()).toBe(false)
		expect(wrapper.find('[data-test="refuse"]').exists()).toBe(false)
		await wrapper.find('[data-test="accept"]').setValue(true)
		await wrapper.find('[data-test="confirm"]').trigger('click')
		expect(wrapper.emitted('confirm')?.[0]?.[0]).toMatchObject({ name: 'Carla', accepted: true, quotations: true })
	})
})
