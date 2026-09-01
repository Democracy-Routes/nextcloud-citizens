// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The colour of a confirm dialog has to mean something.
 *
 * `danger` defaulted to true and `confirmLabel` to "Delete", so every dialog
 * that did not say otherwise looked destructive. "Publish report to table
 * phones" and "Transcribe this table again" — both safe and reversible — got
 * the red warning treatment, while "Close session permanently" correctly
 * passed :danger="false" and looked mild. A facilitator scanning for red
 * learned nothing from it.
 */
import { describe, expect, it } from 'vitest'
import CzConfirm from '../../frontend/src/components/ui/CzConfirm.vue'
import { mountWithI18n } from './support/mount'

const BASE = { title: 'Do the thing?', message: 'It will be done.', confirmLabel: 'Do it' }

describe('CzConfirm tone', () => {
	it('is not destructive unless it says so', () => {
		const wrapper = mountWithI18n(CzConfirm, { props: BASE })

		expect(wrapper.find('.cz-btn--danger').exists()).toBe(false)
		expect(wrapper.find('.cz-btn--primary').exists()).toBe(true)
	})

	it('is red when the action really is destructive', () => {
		const wrapper = mountWithI18n(CzConfirm, { props: { ...BASE, tone: 'danger' } })

		expect(wrapper.find('.cz-btn--danger').exists()).toBe(true)
	})

	it('uses the caller’s label, never a default of "Delete"', () => {
		const wrapper = mountWithI18n(CzConfirm, { props: BASE })

		expect(wrapper.text()).toContain('Do it')
		expect(wrapper.text()).not.toContain('Delete')
	})
})

describe('typed confirmation', () => {
	const props = {
		...BASE,
		tone: 'destructive' as const,
		confirmWord: 'Bologna Mobility Assembly',
	}

	it('will not proceed until the name is typed', async () => {
		const wrapper = mountWithI18n(CzConfirm, { props })
		const confirm = wrapper.find('.cz-btn--danger')

		expect(confirm.attributes('disabled')).toBeDefined()

		await confirm.trigger('click')
		expect(wrapper.emitted('confirm')).toBeFalsy()
	})

	it('proceeds once the name matches', async () => {
		const wrapper = mountWithI18n(CzConfirm, { props })

		await wrapper.find('input').setValue('Bologna Mobility Assembly')
		await wrapper.find('.cz-btn--danger').trigger('click')

		expect(wrapper.emitted('confirm')).toBeTruthy()
	})

	it('is not fooled by a near miss', async () => {
		const wrapper = mountWithI18n(CzConfirm, { props })

		await wrapper.find('input').setValue('Bologna Mobility')

		expect(wrapper.find('.cz-btn--danger').attributes('disabled')).toBeDefined()
	})

	it('asks for no typing when the tone does not call for it', () => {
		const wrapper = mountWithI18n(CzConfirm, { props: { ...BASE, tone: 'danger' } })

		expect(wrapper.find('input').exists()).toBe(false)
	})
})
