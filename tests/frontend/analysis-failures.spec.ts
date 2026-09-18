// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The Analysis tab has to say why the last run failed, what is still
 * waiting, and let the organizer stop it.
 *
 * On 2026-09-18 the tab showed "No findings yet" and "Run analysis now" while
 * every job had died on a 403; five re-runs later the toast said "already
 * running for every table" for eight minutes while a 429 backed off. Nothing
 * on screen named the reason, the wait, or offered a way out.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AnalysisTab from '../../frontend/src/components/AnalysisTab.vue'
import { mountWithI18n } from './support/mount'

const roundFindings = vi.fn()
const requestAnalysis = vi.fn()
const cancelAnalysis = vi.fn()
const recluster = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: {
		roundFindings: (...a: unknown[]) => roundFindings(...a),
		requestAnalysis: (...a: unknown[]) => requestAnalysis(...a),
		cancelAnalysis: (...a: unknown[]) => cancelAnalysis(...a),
		recluster: (...a: unknown[]) => recluster(...a),
		updateFinding: vi.fn(),
		approveDrafts: vi.fn(),
	},
	ApiError: class extends Error {},
	BASE: '',
}))

const ASSEMBLY = {
	id: 'a1',
	name: 'Bologna',
	rounds: [{ id: 'round-1', position: 1, title: 'R1', status: 'ENDED' }],
}

function job(overrides: Record<string, unknown>) {
	return {
		state: 'FAILED',
		attempts: 1,
		max_attempts: 5,
		next_attempt_at: null,
		failure_reason: null,
		failure_detail: null,
		...overrides,
	}
}

function payload(recording: Record<string, unknown>, extra: Record<string, unknown> = {}) {
	return {
		round_id: 'round-1',
		round_status: 'ENDED',
		round_summary: '',
		analysis_configured: true,
		tables_with_findings: 0,
		cross_table: [],
		speaking_balance: null,
		tables: [
			{ table_number: 3, recording: { id: 'rec-1', ...recording }, summary: '', analyzed: false, findings: [] },
		],
		round_job: null,
		...extra,
	}
}

beforeEach(() => {
	roundFindings.mockReset()
	requestAnalysis.mockReset().mockResolvedValue({ queued: 1 })
	cancelAnalysis.mockReset().mockResolvedValue({ cancelled: 1, running: 0 })
	recluster.mockReset().mockResolvedValue({ queued: true })
})

describe('a failed analysis on the Analysis tab', () => {
	it("names the provider's refusal instead of hiding behind 'No findings yet'", async () => {
		roundFindings.mockResolvedValue(
			payload({
				state: 'ANALYSIS_FAILED',
				error_code: 'ANALYSIS_FAILED',
				job: job({
					failure_reason: 'PROVIDER_AUTH',
					failure_detail: 'Analysis authentication failed (403): Inactive subscription',
				}),
			}),
		)
		const wrapper = mountWithI18n(AnalysisTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		const text = wrapper.text()
		expect(text).toContain('Analysis failed')
		expect(text).toContain('Table 3')
		expect(text).toContain('rejected the API key')
		expect(text).toContain('Inactive subscription')
	})

	it('shows what is waiting, why, and lets the organizer cancel it', async () => {
		roundFindings.mockResolvedValue(
			payload({
				state: 'ANALYZING',
				error_code: '',
				job: job({
					state: 'RETRY',
					attempts: 2,
					max_attempts: 5,
					next_attempt_at: new Date(Date.now() + 90_000).toISOString(),
					failure_reason: 'PROVIDER_RATE_LIMIT',
					failure_detail: 'Analysis endpoint returned HTTP 429 (rate limited): slow down',
				}),
			}),
		)
		const wrapper = mountWithI18n(AnalysisTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		const text = wrapper.text()
		expect(text).toContain('Analysis in progress')
		expect(text).toContain('1 waiting to retry')
		expect(text).toContain('Retrying automatically')
		expect(text).toContain('attempt 3 of 5')
		expect(text).toContain('rate-limiting')

		const cancel = wrapper.findAll('button').find((b) => b.text().includes('Cancel pending analysis'))!
		await cancel.trigger('click')
		await flushPromises()
		expect(cancelAnalysis).toHaveBeenCalledWith('round-1')
	})

	it('surfaces a failed cross-table clustering and re-runs only that', async () => {
		roundFindings.mockResolvedValue(
			payload(
				{ state: 'READY_FOR_REVIEW', error_code: '', job: null },
				{
					round_job: job({
						failure_reason: 'SCHEMA_INVALID',
						failure_detail: 'Model output failed validation after retries: clusters.0.title',
					}),
				},
			),
		)
		const wrapper = mountWithI18n(AnalysisTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		expect(wrapper.text()).toContain('Cross-table clustering failed')
		expect(wrapper.text()).toContain('not in the required format')
		const button = wrapper.findAll('button').find((b) => b.text().includes('Re-run clustering only'))!
		await button.trigger('click')
		await flushPromises()
		expect(recluster).toHaveBeenCalledWith('round-1')
		expect(requestAnalysis).not.toHaveBeenCalled()
	})

	it('stays quiet when the last job succeeded', async () => {
		roundFindings.mockResolvedValue(
			payload({ state: 'READY_FOR_REVIEW', error_code: '', job: job({ state: 'SUCCEEDED' }) }),
		)
		const wrapper = mountWithI18n(AnalysisTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()
		expect(wrapper.text()).not.toContain('Analysis failed')
		expect(wrapper.text()).not.toContain('Analysis in progress')
	})
})
