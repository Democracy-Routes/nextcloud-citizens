// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * A phone that scanned an action code is told what the code made it — another
 * recorder of a table, or the first recorder of a new one — and never asked to
 * choose. One tap continues to the usual consent and set-up.
 */
import { describe, expect, it } from 'vitest'
import JoinedScreen from '../../frontend/src/recorder/components/JoinedScreen.vue'
import { mountWithI18n } from './support/mount'

describe('the joined screen', () => {
	it('names the table and the recorder letter for an added recorder', async () => {
		const wrapper = mountWithI18n(JoinedScreen, {
			props: {
				joined: {
					purpose: 'ADD_RECORDER_TO_TABLE', table_number: 7, color_key: 'blue',
					slot: 2, table_created: false,
				},
			},
		})
		expect(wrapper.find('.rc-table-badge').text().replace(/\s+/g, ' ')).toBe('TABLE 7 · BLUE')
		expect(wrapper.find('h1').text()).toBe('You join as Recorder B')
		await wrapper.find('button').trigger('click')
		expect(wrapper.emitted('continue')).toBeTruthy()
	})

	it('says the phone is the recorder of a table that was just created', () => {
		const wrapper = mountWithI18n(JoinedScreen, {
			props: {
				joined: { purpose: 'ADD_TABLE', table_number: 8, color_key: 'green', slot: 1, table_created: true },
			},
		})
		expect(wrapper.find('.rc-table-badge').text().replace(/\s+/g, ' ')).toBe('TABLE 8 · GREEN')
		expect(wrapper.find('h1').text()).toBe('This phone is the recorder of the new table')
	})
})
