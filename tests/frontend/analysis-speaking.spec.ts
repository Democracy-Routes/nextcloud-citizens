// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The Analysis tab surfaces the speaking-balance donut when the round has one,
 * and shows nothing when it doesn't — a round with no diarized speech must not
 * render an empty chart.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AnalysisTab from '../../frontend/src/components/AnalysisTab.vue'
import { mountWithI18n } from './support/mount'

const roundFindings = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: {
		roundFindings: (...a: unknown[]) => roundFindings(...a),
		requestAnalysis: vi.fn().mockResolvedValue({ queued: 0 }),
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

function payload(speaking_balance: unknown) {
	return {
		round_id: 'round-1',
		round_status: 'READY_FOR_REVIEW',
		round_summary: 'They discussed cycle lanes.',
		analysis_configured: true,
		tables_with_findings: 1,
		cross_table: [],
		tables: [
			{
				table_number: 1,
				recording: { id: 'rec-1', state: 'READY_FOR_REVIEW' },
				summary: 'They discussed cycle lanes.',
				analyzed: true,
				// per table, never per round: diarization labels do not cross tables
				speaking_balance,
				findings: [
					{
						id: 'f1',
						scope: 'table',
						type: 'proposal',
						title: 'Widen the cycle lanes',
						summary: 'A proposal.',
						support: '',
						status: 'APPROVED',
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

beforeEach(() => roundFindings.mockReset())

describe('speaking balance on the Analysis tab', () => {
	it('renders the donut under the table that has one', async () => {
		roundFindings.mockResolvedValue(
			payload({
				total_seconds: 120,
				from_recording_id: 'rec-1',
				voices: [
					{ label: 'A', seconds: 80, percent: 67 },
					{ label: 'B', seconds: 40, percent: 33 },
				],
			}),
		)
		const wrapper = mountWithI18n(AnalysisTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		expect(wrapper.find('.cz-speaking').exists()).toBe(true)
		expect(wrapper.text()).toContain('Voice A')
		// inside the table's section, after its heading
		const html = wrapper.html()
		expect(html.indexOf('Table 1')).toBeLessThan(html.indexOf('cz-speaking'))
	})

	it('says so when the table\'s phone changed and the chart covers one part', async () => {
		roundFindings.mockResolvedValue(
			payload({
				total_seconds: 120, from_recording_id: 'rec-1', parts: 2, recorder_changed: true,
				voices: [{ label: 'A', seconds: 80, percent: 67 }, { label: 'B', seconds: 40, percent: 33 }],
			}),
		)
		const wrapper = mountWithI18n(AnalysisTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()
		expect(wrapper.find('.cz-speaking__caveat').text()).toContain('covers the fullest part only')
	})

	it('shows no chart when the table has no measurable speech', async () => {
		roundFindings.mockResolvedValue(payload(null))
		const wrapper = mountWithI18n(AnalysisTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		expect(wrapper.find('.cz-speaking').exists()).toBe(false)
	})
})
