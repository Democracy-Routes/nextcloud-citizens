// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * R25: a synthesis or a session's cross-table analysis that failed used to
 * leave the Report tab looking unchanged forever — nothing here ever read
 * the job's own failure. GET .../progress now carries `failures`; the tab
 * must show it in plain sight, not bury it in a log nobody reads.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ReportTab from '../../frontend/src/components/ReportTab.vue'
import { mountWithI18n } from './support/mount'

const assemblyReport = vi.fn()
const assemblyProgress = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: {
		assemblyReport: (...a: unknown[]) => assemblyReport(...a),
		assemblyProgress: (...a: unknown[]) => assemblyProgress(...a),
		closeSession: vi.fn(),
		reopenSession: vi.fn(),
		publishReport: vi.fn(),
		unpublishReport: vi.fn(),
		refreshFinalReport: vi.fn(),
		generateSynthesis: vi.fn(),
	},
	ApiError: class extends Error {
		status = 0
	},
	BASE: '',
}))

const ASSEMBLY = {
	id: 'a1', kind: 'assembly' as const, name: 'Bologna', rounds: [
		{ id: 'round-1', position: 1, title: 'Session 1', question: '', status: 'ENDED', started_at: null, ended_at: null, duration_minutes: 30 },
		{ id: 'round-2', position: 2, title: 'Session 2', question: '', status: 'ENDED', started_at: null, ended_at: null, duration_minutes: 30 },
	],
}

const REPORT = {
	assembly: { name: 'Bologna', description: '', language: 'en', status: 'OPEN', participants: 4, expected_participants: 4, tables: 1 },
	method: '', methodology_note: '', include_drafts: false, published_at: null, closed_at: null, is_final: false,
	progress: { tables_expected: 1, tables_complete: 0, tables_contributed: 0, tables_missing: [], rounds_total: 2, rounds_analyzed: 0, complete: false },
	rounds: [],
}

const NO_FAILURES = { ...REPORT.progress, failures: { synthesis: null, rounds: {} } }

function job(overrides: Record<string, unknown>) {
	return {
		state: 'FAILED', attempts: 3, max_attempts: 3, next_attempt_at: null,
		failure_reason: null, failure_detail: null, ...overrides,
	}
}

beforeEach(() => {
	assemblyReport.mockReset().mockResolvedValue(REPORT)
	assemblyProgress.mockReset().mockResolvedValue(NO_FAILURES)
})

describe('the Report tab surfacing a failed job', () => {
	it('says nothing when nothing failed', async () => {
		const wrapper = mountWithI18n(ReportTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		expect(wrapper.find('[data-test="synthesis-failed"]').exists()).toBe(false)
		expect(wrapper.find('[data-test="round-analysis-failed"]').exists()).toBe(false)
	})

	it('shows a failed synthesis with its reason', async () => {
		assemblyProgress.mockResolvedValue({
			...REPORT.progress,
			failures: { synthesis: job({ failure_reason: 'PROVIDER_RATE_LIMIT' }), rounds: {} },
		})
		const wrapper = mountWithI18n(ReportTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		const line = wrapper.find('[data-test="synthesis-failed"]')
		expect(line.exists()).toBe(true)
		expect(line.text()).toContain('synthesis across sessions failed')
		expect(line.text()).toContain('rate-limiting requests')
	})

	it('shows one line per failed session, naming its position', async () => {
		assemblyProgress.mockResolvedValue({
			...REPORT.progress,
			failures: {
				synthesis: null,
				rounds: { 'round-2': job({ failure_reason: 'PROVIDER_AUTH' }) },
			},
		})
		const wrapper = mountWithI18n(ReportTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		const lines = wrapper.findAll('[data-test="round-analysis-failed"]')
		expect(lines).toHaveLength(1)
		expect(lines[0].text()).toContain('Session 2')
		expect(lines[0].text()).toContain('rejected the API key')
	})

	it('falls back to the raw code when the catalogue has no sentence for it', async () => {
		assemblyProgress.mockResolvedValue({
			...REPORT.progress,
			failures: { synthesis: job({ failure_reason: 'SOMETHING_NEW' }), rounds: {} },
		})
		const wrapper = mountWithI18n(ReportTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()

		expect(wrapper.find('[data-test="synthesis-failed"]').text()).toContain('SOMETHING_NEW')
	})
})
