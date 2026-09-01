// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * A seating change the server refused must not look like it worked.
 *
 * The <select> is bound with :value, so when moveParticipant failed the vnode
 * prop was unchanged, Vue had nothing to patch, and the DOM kept showing the
 * new table. The facilitator saw a participant seated where the server did not
 * have them — and only a page reload disagreed.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import TablesTab from '../../frontend/src/components/TablesTab.vue'
import { mountWithI18n } from './support/mount'

const roundTables = vi.fn()
const moveParticipant = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: {
		roundTables: (...args: unknown[]) => roundTables(...args),
		moveParticipant: (...args: unknown[]) => moveParticipant(...args),
		randomize: vi.fn(),
		copyPrevious: vi.fn(),
	},
	ApiError: class extends Error {
		status: number
		constructor(status: number, message: string) {
			super(message)
			this.status = status
		}
	},
}))

const TABLES = [
	{
		id: 'table-1',
		number: 1,
		participants: [{ id: 'p1', label: 'P001', name: 'Ada' }],
	},
	{ id: 'table-2', number: 2, participants: [] },
]

const ASSEMBLY = {
	id: 'a1',
	name: 'Bologna',
	rounds: [{ id: 'round-1', position: 1, title: 'R1', status: 'ACTIVE' }],
}

beforeEach(() => {
	roundTables.mockReset().mockResolvedValue(TABLES)
	moveParticipant.mockReset()
})

describe('moving a participant between tables', () => {
	it('puts the dropdown back when the server refuses the move', async () => {
		moveParticipant.mockRejectedValue(new Error('Round already ended'))
		const wrapper = mountWithI18n(TablesTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		// not wrapper.find('select'): the first one is the round picker
		const select = wrapper.find<HTMLSelectElement>('select[title="Move to table"]')
		expect(select.element.value).toBe('table-1')

		select.element.value = 'table-2'
		await select.trigger('change')
		await flushPromises()

		expect(select.element.value).toBe(
			'table-1',
			// the whole point: the UI must agree with the server
		)
	})

	it('leaves the new table selected when the move succeeds', async () => {
		moveParticipant.mockResolvedValue([
			{ ...TABLES[0], participants: [] },
			{ ...TABLES[1], participants: [{ id: 'p1', label: 'P001', name: 'Ada' }] },
		])
		const wrapper = mountWithI18n(TablesTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		const select = wrapper.find<HTMLSelectElement>('select[title="Move to table"]')
		select.element.value = 'table-2'
		await select.trigger('change')
		await flushPromises()

		expect(moveParticipant).toHaveBeenCalledWith('round-1', 'p1', 'table-2')
	})

	it('shows a real message when the table list cannot be loaded', async () => {
		roundTables.mockRejectedValue(new TypeError('Failed to fetch'))
		const wrapper = mountWithI18n(TablesTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		// not an empty seating chart presented as fact
		expect(wrapper.text()).toContain('Nextcloud cannot be reached')
	})
})
