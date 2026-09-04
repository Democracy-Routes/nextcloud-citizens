// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Narrowing the findings list, and approving what is left.
 *
 * "Manual moderation is tedious" was raised at a real assembly, with the
 * suggested fix being an option to skip moderation. That is the one thing this
 * must not offer — human approval is what the report's methodology note
 * asserts, and approving is also what protects a finding from being wiped by
 * the next analysis run. So: approve many at once, still deliberately.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AnalysisTab from '../../frontend/src/components/AnalysisTab.vue'
import { mountWithI18n } from './support/mount'

const roundFindings = vi.fn()
const approveDrafts = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: {
		roundFindings: (...a: unknown[]) => roundFindings(...a),
		approveDrafts: (...a: unknown[]) => approveDrafts(...a),
		requestAnalysis: vi.fn(),
		updateFinding: vi.fn(),
	},
	ApiError: class extends Error {},
	BASE: '',
}))

const ASSEMBLY = {
	id: 'a1',
	name: 'Bologna',
	rounds: [{ id: 'round-1', position: 1, title: 'Mobility', status: 'ENDED' }],
}

function finding(id: string, status: string, type = 'proposal') {
	return {
		id, scope: 'table', type, title: `Finding ${id}`, summary: 'A summary.',
		support: '', status, evidence: [], mentioned_table_count: 0, ai_model: '',
		table_number: 1,
	}
}

function payload(findings: ReturnType<typeof finding>[]) {
	return {
		round_id: 'round-1', round_status: 'READY_FOR_REVIEW', round_summary: '',
		analysis_configured: true, tables_with_findings: 1, cross_table: [],
		tables: [
			{ table_number: 1, recording: { id: 'rec-1', state: 'READY_FOR_REVIEW' },
			  summary: 'They discussed cycle lanes.', analyzed: true, findings },
		],
	}
}

const MIXED = payload([
	finding('a', 'DRAFT'),
	finding('b', 'DRAFT', 'concern'),
	finding('c', 'APPROVED'),
	finding('d', 'REJECTED'),
])

async function mount() {
	const wrapper = mountWithI18n(AnalysisTab, { props: { assembly: ASSEMBLY } })
	await flushPromises()
	return wrapper
}

beforeEach(() => {
	roundFindings.mockReset().mockResolvedValue(MIXED)
	approveDrafts.mockReset().mockResolvedValue({ approved: 2 })
})

describe('filtering the findings', () => {
	it('shows everything by default', async () => {
		const wrapper = await mount()

		for (const id of ['a', 'b', 'c', 'd']) {
			expect(wrapper.text()).toContain(`Finding ${id}`)
		}
	})

	it('narrows to what still needs review', async () => {
		const wrapper = await mount()

		await wrapper.findAll('select')[1].setValue('draft')

		expect(wrapper.text()).toContain('Finding a')
		expect(wrapper.text()).not.toContain('Finding c')
		expect(wrapper.text()).not.toContain('Finding d')
	})

	it('narrows by type', async () => {
		const wrapper = await mount()

		await wrapper.findAll('select')[2].setValue('concern')

		expect(wrapper.text()).toContain('Finding b')
		expect(wrapper.text()).not.toContain('Finding a')
	})

	it('explains an empty result instead of showing bare headings', async () => {
		// the section headers and the "Analyzed — no substantive findings" line
		// are computed on the raw payload, so a filter matching nothing used to
		// render a table heading with nothing under it
		const wrapper = await mount()

		await wrapper.findAll('select')[2].setValue('minority_position')

		expect(wrapper.text()).toContain('No findings match this filter')
		expect(wrapper.text()).not.toContain('Table 1')
	})
})

describe('approving every draft', () => {
	it('offers the action with the count in it', async () => {
		const wrapper = await mount()

		expect(wrapper.text()).toContain('Approve 2 draft(s)')
	})

	it('is not offered when nothing is waiting', async () => {
		roundFindings.mockResolvedValue(payload([finding('c', 'APPROVED')]))
		const wrapper = await mount()

		// the filter dropdown still offers "Approved" as an option — it is the
		// bulk action that must be absent
		expect(wrapper.findAll('button').some((b) => b.text().includes('draft(s)'))).toBe(false)
	})

	it('asks first, and says what it will leave alone', async () => {
		const wrapper = await mount()

		await wrapper.findAll('button').find((b) => b.text().includes('Approve 2'))!.trigger('click')

		expect(approveDrafts).not.toHaveBeenCalled()
		expect(wrapper.text()).toContain('Rejected findings are left alone')
	})

	it('approves once confirmed', async () => {
		const wrapper = await mount()
		await wrapper.findAll('button').find((b) => b.text().includes('Approve 2'))!.trigger('click')

		await wrapper.findAll('button').find((b) => b.text() === 'Approve all drafts')!.trigger('click')
		await flushPromises()

		expect(approveDrafts).toHaveBeenCalledWith('round-1')
	})
})
