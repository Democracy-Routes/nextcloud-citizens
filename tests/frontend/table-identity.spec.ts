// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * "TABLE 7 · BLUE": the number is the identity, the colour a cue. A server
 * older than 0.7 sends no colour and the badge must still read "TABLE 7".
 * Slot letters match the server's (A, B, … AA).
 */
import { describe, expect, it } from 'vitest'
import TableBadge from '../../frontend/src/recorder/components/TableBadge.vue'
import { slotLabel } from '../../frontend/src/recorder/slots'
import { captionFooter, updateHistory } from '../../frontend/src/recorder/captionState'
import { mountWithI18n } from './support/mount'

describe('the table badge', () => {
	it('shows the number and the colour', () => {
		const wrapper = mountWithI18n(TableBadge, { props: { number: 7, colorKey: 'blue' } })
		expect(wrapper.text().replace(/\s+/g, ' ')).toBe('TABLE 7 · BLUE')
		expect(wrapper.find('.rc-tabledot--blue').exists()).toBe(true)
		expect(wrapper.find('.rc-tabledot').attributes('aria-label')).toBe('BLUE')
	})

	it('is only the number when the server sent no colour, or an unknown one', () => {
		expect(mountWithI18n(TableBadge, { props: { number: 7 } }).text()).toBe('TABLE 7')
		const odd = mountWithI18n(TableBadge, { props: { number: 7, colorKey: 'magenta' } })
		expect(odd.text()).toBe('TABLE 7')
		expect(odd.find('.rc-tabledot').exists()).toBe(false)
	})

	it('can be the armed screen hero', () => {
		const wrapper = mountWithI18n(TableBadge, { props: { number: 2, colorKey: 'green', hero: true } })
		expect(wrapper.classes()).toContain('rc-table-badge--hero')
	})
})

describe('recorder slot letters', () => {
	it('match the server', () => {
		expect([1, 2, 3, 26, 27, 28].map(slotLabel)).toEqual(['A', 'B', 'C', 'Z', 'AA', 'AB'])
		expect(slotLabel(0)).toBe('A')
	})
})

describe('the caption footer for a backup recorder', () => {
	it('says another recorder carries the captions, never an alarm', () => {
		const history = { sawLines: false, consecutiveInactive: 0 }
		const poll = { active: false, lines: [], reason: 'backup' }
		expect(captionFooter(poll, updateHistory(poll, history))).toBe('backup')
		// even after many polls — this is intentional, not an outage
		let h = history
		for (let i = 0; i < 10; i++) h = updateHistory(poll, h)
		expect(captionFooter(poll, h)).toBe('backup')
	})
})
