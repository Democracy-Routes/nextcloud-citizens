// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SeedsTab from '../../frontend/src/components/SeedsTab.vue'
import { mountWithI18n } from './support/mount'

const listSeeds = vi.fn()
const updateSeed = vi.fn()
const approveAllSeeds = vi.fn()
const downloadFromApi = vi.fn()
const pushSeeds = vi.fn()
const toast = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: {
		listSeeds: (...a: unknown[]) => listSeeds(...a),
		updateSeed: (...a: unknown[]) => updateSeed(...a),
		approveAllSeeds: (...a: unknown[]) => approveAllSeeds(...a),
		pushSeeds: (...a: unknown[]) => pushSeeds(...a),
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
vi.mock('../../frontend/src/components/ui/toast', () => ({ toast: (...a: unknown[]) => toast(...a) }))
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

function polisState(overrides: Record<string, unknown> = {}) {
	return {
		configured: false, conversation_id: null, url: null, moderation_url: null, report_url: null,
		pushed_at: null, published_at: null, job: null, refused_seed_ids: [], ...overrides,
	}
}

function listing(overrides: Record<string, unknown> = {}) {
	return {
		assembly_id: 'a1', language: 'en', analysis_configured: true, findings_approved: 2,
		ready_to_export: false, max_chars: 400, soft_chars: 140, job: null, polis: polisState(), seeds: [], ...overrides,
	}
}

beforeEach(() => {
	listSeeds.mockReset().mockResolvedValue(listing())
	updateSeed.mockReset().mockResolvedValue(seed({ status: 'APPROVED' }))
	approveAllSeeds.mockReset()
	toast.mockReset()
	pushSeeds.mockReset().mockResolvedValue({ queued: true })
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

	it('approves every draft after confirming, and hides the button when none is left', async () => {
		listSeeds.mockResolvedValue(listing({
			seeds: [seed(), seed({ id: 's2', position: 2 }), seed({ id: 's3', position: 3, status: 'REJECTED' })],
		}))
		approveAllSeeds.mockResolvedValue(listing({
			approved: 2,
			ready_to_export: true,
			seeds: [
				seed({ status: 'APPROVED' }),
				seed({ id: 's2', position: 2, status: 'APPROVED' }),
				seed({ id: 's3', position: 3, status: 'REJECTED' }),
			],
		}))
		const wrapper = mountWithI18n(SeedsTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()
		const button = wrapper.find('[data-test="seeds-approve-all"]')
		expect(button.exists()).toBe(true)

		await button.trigger('click')
		await flushPromises()
		expect(approveAllSeeds).not.toHaveBeenCalled()
		const confirm = wrapper.findAll('button').filter((b) => b.text() === 'Approve all' && b.element !== button.element)
		expect(confirm).toHaveLength(1)
		await confirm[0].trigger('click')
		await flushPromises()

		expect(approveAllSeeds).toHaveBeenCalledTimes(1)
		expect(approveAllSeeds).toHaveBeenCalledWith('a1')
		const pills = wrapper.findAll('[data-test="seed-row"]').map((r) => r.text())
		expect(pills[0]).toContain('Approved')
		expect(pills[1]).toContain('Approved')
		expect(pills[2]).toContain('Rejected')
		expect(wrapper.find('[data-test="seeds-approve-all"]').exists()).toBe(false)
	})

	it('disables Send to Polis and says why when Polis is not configured', async () => {
		listSeeds.mockResolvedValue(listing({ ready_to_export: true, seeds: [seed({ status: 'APPROVED' })] }))
		const wrapper = mountWithI18n(SeedsTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()
		const push = wrapper.find('[data-test="seeds-push"]')
		expect(push.attributes('disabled')).toBeDefined()
		expect(push.attributes('title')).toContain('Add the Polis instance')
	})

	it('sends to Polis after confirming and toasts', async () => {
		listSeeds.mockResolvedValue(listing({
			ready_to_export: true, polis: polisState({ configured: true }), seeds: [seed({ status: 'APPROVED' })],
		}))
		const wrapper = mountWithI18n(SeedsTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()
		const push = wrapper.find('[data-test="seeds-push"]')
		expect(push.attributes('disabled')).toBeUndefined()
		await push.trigger('click')
		await flushPromises()
		expect(pushSeeds).not.toHaveBeenCalled()
		const confirm = wrapper.findAll('button').filter((b) => b.text() === 'Send')
		expect(confirm).toHaveLength(1)
		await confirm[0].trigger('click')
		await flushPromises()
		expect(pushSeeds).toHaveBeenCalledTimes(1)
		expect(pushSeeds).toHaveBeenCalledWith('a1')
		expect(String(toast.mock.calls[0][0])).toContain('Sending to Polis')
	})

	it('shows the three Polis links once the conversation exists', async () => {
		listSeeds.mockResolvedValue(listing({
			ready_to_export: true,
			polis: polisState({
				configured: true, url: 'https://p.example/abc', moderation_url: 'https://p.example/m/abc',
				report_url: 'https://p.example/r/abc', pushed_at: '2026-11-13T10:00:00Z',
			}),
			seeds: [seed({ status: 'EXPORTED' })],
		}))
		const wrapper = mountWithI18n(SeedsTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()
		const links = wrapper.findAll('[data-test="seeds-polis-links"] a')
		expect(links.map((a) => a.attributes('href'))).toEqual([
			'https://p.example/abc', 'https://p.example/m/abc', 'https://p.example/r/abc',
		])
		expect(links[0].attributes('rel')).toBe('noopener')
		expect(wrapper.find('[data-test="seeds-polis-links"]').text()).toContain('Sent on')
	})

	it('marks a statement Polis refused', async () => {
		listSeeds.mockResolvedValue(listing({
			polis: polisState({ configured: true, refused_seed_ids: ['s2'] }),
			seeds: [seed(), seed({ id: 's2', position: 2 })],
		}))
		const wrapper = mountWithI18n(SeedsTab, { props: { assembly: ASSEMBLY } })
		await flushPromises()
		const rows = wrapper.findAll('[data-test="seed-row"]')
		expect(rows[0].find('[data-test="seed-refused"]').exists()).toBe(false)
		expect(rows[1].find('[data-test="seed-refused"]').text()).toBe('Refused by Polis')
	})
})
