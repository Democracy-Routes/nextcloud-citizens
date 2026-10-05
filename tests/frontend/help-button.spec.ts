// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The table's hand. One tap says what kind of help, the line reads
 * "Organizer notified" until the Live tab acknowledges it, then "The
 * organizer has seen it". The server's word wins over the phone's own.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import HelpButton from '../../frontend/src/recorder/components/HelpButton.vue'
import { mountWithI18n } from './support/mount'

const needHelp = vi.fn()

vi.mock('../../frontend/src/recorder/api', () => ({
	recorderApi: { needHelp: (...args: unknown[]) => needHelp(...args) },
}))

const RAISED = {
	id: 'h1', kind: 'TECHNICAL' as const, table_number: 3, slot: 1,
	created_at: '2026-10-05T10:00:00Z', acknowledged_at: null,
}

beforeEach(() => {
	needHelp.mockReset()
	needHelp.mockResolvedValue(RAISED)
})

describe('HelpButton', () => {
	it('asks what kind of help, sends it and says the organizer was notified', async () => {
		const wrapper = mountWithI18n(HelpButton, { props: { token: 'tok', help: null } })
		expect(wrapper.text()).toContain('Need help')
		expect(wrapper.find('.rc-sheet').exists()).toBe(false)
		await wrapper.find('.rc-help__btn').trigger('click')
		const choices = wrapper.findAll('.rc-sheet .rc-primary').map((b) => b.text())
		expect(choices).toEqual(['Technical problem', 'Call the organizer', 'Question about the process'])
		await wrapper.findAll('.rc-sheet .rc-primary')[0].trigger('click')
		await flushPromises()
		expect(needHelp).toHaveBeenCalledWith('tok', 'TECHNICAL')
		expect(wrapper.find('.rc-sheet').exists()).toBe(false)
		expect(wrapper.text()).toContain('Organizer notified')
		expect(wrapper.find('.rc-help__btn').exists()).toBe(false)
	})

	it('follows the server: acknowledged reads as seen, and a cleared hand brings the button back', async () => {
		const wrapper = mountWithI18n(HelpButton, { props: { token: 'tok', help: RAISED } })
		expect(wrapper.text()).toContain('Organizer notified')
		await wrapper.setProps({ help: { ...RAISED, acknowledged_at: '2026-10-05T10:01:00Z' } })
		expect(wrapper.text()).toContain('The organizer has seen it')
		await wrapper.find('.rc-help__dismiss').trigger('click')
		expect(wrapper.text()).toContain('Need help')
		await wrapper.setProps({ help: null })
		expect(wrapper.text()).toContain('Need help')
	})

	it('keeps the button when the server cannot be reached', async () => {
		needHelp.mockRejectedValue(new Error('offline'))
		const wrapper = mountWithI18n(HelpButton, { props: { token: 'tok', help: null } })
		await wrapper.find('.rc-help__btn').trigger('click')
		await wrapper.findAll('.rc-sheet .rc-primary')[1].trigger('click')
		await flushPromises()
		expect(wrapper.text()).toContain('Could not reach the server')
		expect(wrapper.find('.rc-sheet').exists()).toBe(true)
	})
})
