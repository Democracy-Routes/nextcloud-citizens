// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Re-running the analysis destroys human work, and used to say nothing.
 *
 * The button passed force=true, which regenerates every finding for the round
 * — including the ones a facilitator has read, edited and approved. There was
 * no dialog: one click and the review was gone.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AnalysisTab from '../../frontend/src/components/AnalysisTab.vue'
import { mountWithI18n } from './support/mount'

const roundFindings = vi.fn()
const requestAnalysis = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: {
		roundFindings: (...a: unknown[]) => roundFindings(...a),
		requestAnalysis: (...a: unknown[]) => requestAnalysis(...a),
		updateFinding: vi.fn(),
	},
	ApiError: class extends Error {},
	BASE: '',
}))

const ASSEMBLY = {
	id: 'a1',
	name: 'Bologna',
	rounds: [{ id: 'round-1', position: 1, title: 'R1', status: 'ENDED' }],
}

function findings(status: string) {
	return {
		round_id: 'round-1',
		round_status: 'READY_FOR_REVIEW',
		round_summary: '',
		analysis_configured: true,
		tables_with_findings: 1,
		cross_table: [],
		tables: [
			{
				table_number: 1,
				recording: { id: 'rec-1', state: 'READY_FOR_REVIEW' },
				summary: 'They discussed cycle lanes.',
				analyzed: true,
				findings: [
					{
						id: 'f1',
						scope: 'table',
						type: 'proposal',
						title: 'Widen the cycle lanes',
						summary: '',
						support: '',
						status,
						evidence: [],
						evidence_removed_at: null,
						mentioned_table_count: 0,
						ai_model: '',
						table_number: 1,
					},
				],
			},
		],
	}
}

beforeEach(() => {
	roundFindings.mockReset()
	requestAnalysis.mockReset().mockResolvedValue({ queued: 1 })
})

describe('re-running the analysis', () => {
	it('does not regenerate approved findings without asking', async () => {
		roundFindings.mockResolvedValue(findings('APPROVED'))
		const wrapper = mountWithI18n(AnalysisTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		const button = wrapper.findAll('button').find((b) => b.text().includes('Re-run analysis'))!
		await button.trigger('click')

		expect(requestAnalysis).not.toHaveBeenCalled()
		expect(wrapper.text()).toContain('1 you have already approved')
	})

	it('warns more mildly when only drafts would be replaced', async () => {
		roundFindings.mockResolvedValue(findings('DRAFT'))
		const wrapper = mountWithI18n(AnalysisTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		const button = wrapper.findAll('button').find((b) => b.text().includes('Re-run analysis'))!
		await button.trigger('click')

		expect(requestAnalysis).not.toHaveBeenCalled()
		expect(wrapper.text()).toContain('Every draft finding')
		// no typed confirmation for work nobody has reviewed
		expect(wrapper.find('.cz-modal__typeit').exists()).toBe(false)
	})

	it('requires typing before replacing reviewed findings', async () => {
		roundFindings.mockResolvedValue(findings('EDITED_AND_APPROVED'))
		const wrapper = mountWithI18n(AnalysisTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		await wrapper.findAll('button').find((b) => b.text().includes('Re-run analysis'))!.trigger('click')
		expect(wrapper.find('.cz-modal__typeit').exists()).toBe(true)

		await wrapper.find('.cz-modal__typeit input').setValue('replace')
		await wrapper.find('.cz-btn--danger').trigger('click')

		expect(requestAnalysis).toHaveBeenCalledWith('round-1', true)
	})
})
