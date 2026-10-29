// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SeedsTab from '../../frontend/src/components/SeedsTab.vue'
import { mountWithI18n } from './support/mount'

const listSeeds = vi.fn()
const updateSeed = vi.fn()
const downloadFromApi = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: {
		listSeeds: (...a: unknown[]) => listSeeds(...a),
		updateSeed: (...a: unknown[]) => updateSeed(...a),
		generateSeeds: vi.fn(),
		createSeed: vi.fn(),
		reorderSeeds: vi.fn(),
		deleteSeed: vi.fn(),
	},
	ApiError: class extends Error {
		status = 0
	},
	BASE: '',
}))
vi.mock('../../frontend/src/download', () => ({
	downloadFromApi: (...a: unknown[]) => downloadFromApi(...a),
	downloadBlob: vi.fn(),
}))

const ASSEMBLY = { id: 'a1', kind: 'assembly' as const, name: 'Bologna', rounds: [] }

function seed(overrides: Record<string, unknown> = {}) {
	return {
		id: 's1', text: 'Cars should be banned downtown', status: 'DRAFT', position: 1, origin: 'ai',
		finding_id: 'f1', edited: false, stale: false, reviewed_by: null, exported_at: null, ...overrides,
	}
}

function listing(overrides: Record<string, unknown> = {}) {
	return {
		assembly_id: 'a1', language: 'en', analysis_configured: true, findings_approved: 2,
		ready_to_export: false, max_chars: 400, soft_chars: 140, job: null, seeds: [], ...overrides,
	}
}

beforeEach(() => {
	listSeeds.mockReset().mockResolvedValue(listing())
	updateSeed.mockReset().mockResolvedValue(seed({ status: 'APPROVED' }))
	downloadFromApi.mockReset().mockResolvedValue(undefined)
})

describe('the Polis seeds tab', () => {
	it('shows the empty state when there are no statements', async () => {
		const wrapper = mountWithI18n(SeedsTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()
		expect(wrapper.find('[data-test="seeds-empty"]').exists()).toBe(true)
	})

	it('disables generating and says why when analysis is not configured', async () => {
		listSeeds.mockResolvedValue(listing({ analysis_configured: false }))
		const wrapper = mountWithI18n(SeedsTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()
		expect(wrapper.find('[data-test="seeds-generate"]').attributes('disabled')).toBeDefined()
		expect(wrapper.text()).toContain('AI analysis is not configured')
	})

	it('renders rows with a character counter', async () => {
		listSeeds.mockResolvedValue(listing({ seeds: [seed(), seed({ id: 's2', text: 'Abc', position: 2 })] }))
		const wrapper = mountWithI18n(SeedsTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()
		expect(wrapper.findAll('[data-test="seed-row"]')).toHaveLength(2)
		expect(wrapper.findAll('[data-test="seed-counter"]')[1].text()).toBe('3/400')
		expect(wrapper.find('[data-test="seeds-summary"]').text()).toContain('2 to review')
	})

	it('approves a draft and opens the export once the listing says it is ready', async () => {
		listSeeds.mockResolvedValueOnce(listing({ seeds: [seed()] }))
		const wrapper = mountWithI18n(SeedsTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()
		expect(wrapper.find('[data-test="seeds-export-csv"]').attributes('disabled')).toBeDefined()

		listSeeds.mockResolvedValue(listing({ ready_to_export: true, seeds: [seed({ status: 'APPROVED' })] }))
		await wrapper.find('[data-test="seed-approve"]').trigger('click')
		await flushPromises()

		expect(updateSeed).toHaveBeenCalledWith('a1', 's1', { status: 'APPROVED' })
		expect(wrapper.find('[data-test="seeds-export-csv"]').attributes('disabled')).toBeUndefined()

		await wrapper.find('[data-test="seeds-export-csv"]').trigger('click')
		await flushPromises()
		expect(downloadFromApi).toHaveBeenCalledTimes(1)
		expect(String(downloadFromApi.mock.calls[0][0])).toMatch(/\/seeds\/export\.csv$/)
	})

	it('shows a failed generation job', async () => {
		listSeeds.mockResolvedValue(listing({
			job: {
				state: 'FAILED', attempts: 3, max_attempts: 3, next_attempt_at: null,
				failure_reason: 'PROVIDER_RATE_LIMIT', failure_detail: null,
			},
		}))
		const wrapper = mountWithI18n(SeedsTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()
		expect(wrapper.find('[data-test="seeds-failure"]').exists()).toBe(true)
	})
})
