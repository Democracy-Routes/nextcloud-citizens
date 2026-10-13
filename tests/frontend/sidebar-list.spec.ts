// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The sidebar's single Recordings list: in-progress rows before closed ones,
 * newest first within each group; the All/Sessions/Assemblies/Closed chips
 * narrow it without ever emptying a kind's view just because every row of
 * that kind happens to be closed; a name search narrows further; and the
 * chosen chip plus the search text persist per browser, like the sidebar's
 * collapse state already does, so reopening mid-event lands on the same view.
 */
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../../frontend/src/App.vue'
import { mountWithI18n } from './support/mount'

const listAssemblies = vi.fn()

vi.mock('../../frontend/src/api', () => {
	// Defined inside the factory so the thrown error and the exported class
	// are the SAME class: App.vue's `instanceof ApiError` check only holds
	// when both sides come from this one definition.
	class ApiError extends Error {
		status: number
		constructor(status: number, message: string) {
			super(message)
			this.status = status
		}
	}
	return {
		api: {
			listAssemblies: (...a: unknown[]) => listAssemblies(...a),
			// Not an administrator: keeps the Settings row out of the sidebar,
			// so every `.cz-navitem` in this file is a Recordings row.
			adminPing: vi.fn().mockRejectedValue(new ApiError(403, 'not an administrator')),
		},
		ApiError,
		BASE: '',
	}
})

function session(id: string, name: string, overrides: Record<string, unknown> = {}) {
	return {
		id, kind: 'session', name, status: 'ACTIVE',
		recording_mode: 'orchestrated', expected_participants: 0, default_table_count: 2, language: 'en',
		created_at: '2026-01-01T00:00:00Z', closed_at: null,
		...overrides,
	}
}

function assembly(id: string, name: string, overrides: Record<string, unknown> = {}) {
	return {
		id, kind: 'assembly', name, status: 'ACTIVE',
		recording_mode: 'orchestrated', expected_participants: 10, default_table_count: 4, language: 'en',
		created_at: '2026-01-01T00:00:00Z', closed_at: null,
		...overrides,
	}
}

beforeEach(() => {
	listAssemblies.mockReset().mockResolvedValue([])
	localStorage.clear()
})

function names(wrapper: VueWrapper): string[] {
	return wrapper.findAll('.cz-navitem__name').map((n) => n.text())
}

async function clickChip(wrapper: VueWrapper, label: string): Promise<void> {
	const chip = wrapper.findAll('.cz-chip').find((c) => c.text() === label)
	if (!chip) throw new Error(`no chip labelled ${label}`)
	await chip.trigger('click')
	await flushPromises()
}

describe('the Recordings list', () => {
	it('sorts newest first, regardless of kind or load order', async () => {
		listAssemblies.mockResolvedValue([
			session('s-1', 'Earliest open', { created_at: '2026-01-01T00:00:00Z' }),
			assembly('a-1', 'Latest open', { created_at: '2026-06-01T00:00:00Z' }),
			session('s-2', 'Middle open', { created_at: '2026-03-01T00:00:00Z' }),
		])
		const wrapper = mountWithI18n(App)
		await flushPromises()

		expect(names(wrapper)).toEqual(['Latest open', 'Middle open', 'Earliest open'])
	})

	it('never empties a chip just because every row of that kind is closed', async () => {
		listAssemblies.mockResolvedValue([
			session('s-1', 'Closed session one', {
				status: 'COMPLETE', closed_at: '2026-02-01T00:00:00Z', created_at: '2026-02-01T00:00:00Z',
			}),
			session('s-2', 'Closed session two', {
				status: 'COMPLETE', closed_at: '2026-05-01T00:00:00Z', created_at: '2026-05-01T00:00:00Z',
			}),
			assembly('a-1', 'Open assembly', { created_at: '2026-01-01T00:00:00Z' }),
			assembly('a-2', 'Closed assembly', {
				status: 'COMPLETE', closed_at: '2026-03-01T00:00:00Z', created_at: '2026-03-01T00:00:00Z',
			}),
		])
		const wrapper = mountWithI18n(App)
		await flushPromises()

		// every session is closed: the exception shows them rather than nothing
		await clickChip(wrapper, 'Sessions')
		expect(names(wrapper)).toEqual(['Closed session two', 'Closed session one'])

		// one assembly is still open, so the closed assembly is hidden here
		await clickChip(wrapper, 'Assemblies')
		expect(names(wrapper)).toEqual(['Open assembly'])

		// something is open somewhere, so All hides every closed row
		await clickChip(wrapper, 'All')
		expect(names(wrapper)).toEqual(['Open assembly'])

		// Closed: exactly the closed rows, newest first, whatever their kind
		await clickChip(wrapper, 'Closed')
		expect(names(wrapper)).toEqual(['Closed session two', 'Closed assembly', 'Closed session one'])
	})

	it('filters by name, case-insensitively, on top of the chosen chip', async () => {
		listAssemblies.mockResolvedValue([
			session('s-1', 'Mobility Session'),
			assembly('a-1', 'Housing Assembly'),
		])
		const wrapper = mountWithI18n(App)
		await flushPromises()

		await wrapper.find('.cz-sidebar__search').setValue('MOBILITY')
		await flushPromises()

		expect(names(wrapper)).toEqual(['Mobility Session'])
	})

	it('remembers the chosen chip and the search text across a reload', async () => {
		listAssemblies.mockResolvedValue([
			session('s-1', 'Mobility Session', { status: 'COMPLETE', closed_at: '2026-01-02T00:00:00Z' }),
		])
		const wrapper = mountWithI18n(App)
		await flushPromises()

		await clickChip(wrapper, 'Closed')
		await wrapper.find('.cz-sidebar__search').setValue('mobility')
		await flushPromises()

		expect(JSON.parse(localStorage.getItem('citizens-sidebar-filter') ?? '{}')).toEqual({
			chip: 'closed', search: 'mobility',
		})

		// a fresh mount reads the same localStorage, as a reload would
		const reopened = mountWithI18n(App)
		await flushPromises()

		const closedChip = reopened.findAll('.cz-chip').find((c) => c.text() === 'Closed')
		expect(closedChip?.attributes('aria-pressed')).toBe('true')
		expect((reopened.find('.cz-sidebar__search').element as HTMLInputElement).value).toBe('mobility')
	})

	it('falls back to the defaults when the saved preference is not valid JSON', async () => {
		localStorage.setItem('citizens-sidebar-filter', '{not json')
		listAssemblies.mockResolvedValue([assembly('a-1', 'Housing Assembly')])
		const wrapper = mountWithI18n(App)
		await flushPromises()

		const allChip = wrapper.findAll('.cz-chip').find((c) => c.text() === 'All')
		expect(allChip?.attributes('aria-pressed')).toBe('true')
		expect(names(wrapper)).toEqual(['Housing Assembly'])
	})
})
