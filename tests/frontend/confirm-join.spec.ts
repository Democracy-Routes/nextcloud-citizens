// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Two guards against a scan by mistake, asked before a code is spent: a third
 * recorder at a table that already has two, and a phone that was recording
 * one table scanning a code for another. Cancel never consumes the code.
 */
import { describe, expect, it } from 'vitest'
import ConfirmJoinScreen from '../../frontend/src/recorder/components/ConfirmJoinScreen.vue'
import { mountWithI18n } from './support/mount'

describe('the confirm-join guard', () => {
	it('asks before a third recorder joins a table', async () => {
		const wrapper = mountWithI18n(ConfirmJoinScreen, {
			props: { kind: 'third-recorder', tableNumber: 7, colorKey: 'blue', recorders: 2 },
		})
		expect(wrapper.find('h1').text()).toBe('This table already has 2 recorders')
		expect(wrapper.find('.rc-table-badge').text().replace(/\s+/g, ' ')).toBe('TABLE 7 · BLUE')
		const buttons = wrapper.findAll('button').map((b) => b.text())
		expect(buttons).toEqual(['Join Table 7', 'Cancel'])
		await wrapper.findAll('button')[1].trigger('click')
		expect(wrapper.emitted('cancel')).toBeTruthy()
		expect(wrapper.emitted('join')).toBeFalsy()
	})

	it('asks before a phone switches table, offering to stay', async () => {
		const wrapper = mountWithI18n(ConfirmJoinScreen, {
			props: { kind: 'switch-table', tableNumber: 7, colorKey: 'blue', previousTable: 3 },
		})
		expect(wrapper.find('h1').text()).toBe('This phone was recording Table 3')
		const buttons = wrapper.findAll('button').map((b) => b.text())
		expect(buttons).toEqual(['Join Table 7', 'Keep Table 3'])
		await wrapper.findAll('button')[0].trigger('click')
		expect(wrapper.emitted('join')).toBeTruthy()
	})
})
