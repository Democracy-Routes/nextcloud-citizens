// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * A half-written finding must not be thrown away by a background refresh.
 *
 * The ids are stable across an ordinary poll, so the card survives one. The
 * loss needed a second event: a background analysis job DELETES the draft
 * findings it replaces, every id changes, the poll swaps the list, and Vue
 * unmounts the card the organizer was typing in. No warning, no error — the
 * text was simply gone, and this lands on the person doing the most careful
 * work in the room.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AnalysisTab from '../../frontend/src/components/AnalysisTab.vue'
import { mountWithI18n } from './support/mount'

const roundFindings = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: {
		roundFindings: (...a: unknown[]) => roundFindings(...a),
		requestAnalysis: vi.fn(),
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

function findings(id: string) {
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
						id,
						scope: 'table',
						type: 'proposal',
						title: 'Widen the cycle lanes',
						summary: '',
						support: '',
						status: 'DRAFT',
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
	roundFindings.mockReset().mockResolvedValue(findings('f1'))
	vi.useFakeTimers()
})

async function openEditor() {
	const wrapper = mountWithI18n(AnalysisTab, { props: { assembly: ASSEMBLY } })
	await flushPromises()
	await wrapper.findAll('button').find((b) => b.text().includes('Edit'))!.trigger('click')
	await wrapper.find('input[type="text"]').setValue('Widen the cycle lanes considerably')
	return wrapper
}

describe('editing a finding while the tab polls', () => {
	it('keeps the typed text when a re-analysis replaces every id', async () => {
		const wrapper = await openEditor()
		// the job lands: same finding, brand new id
		roundFindings.mockResolvedValue(findings('f2-regenerated'))

		await vi.advanceTimersByTimeAsync(60_000)
		await flushPromises()

		const input = wrapper.find('input[type="text"]')
		expect(input.exists()).toBe(true)
		expect((input.element as HTMLInputElement).value).toBe('Widen the cycle lanes considerably')
	})

	it('says why the view has stopped updating', async () => {
		const wrapper = await openEditor()

		expect(wrapper.text()).toContain('Paused while you edit')
	})

	it('resumes as soon as the editor is closed', async () => {
		const wrapper = await openEditor()
		const whilePaused = roundFindings.mock.calls.length
		await vi.advanceTimersByTimeAsync(60_000)
		expect(roundFindings.mock.calls.length).toBe(whilePaused)

		await wrapper.findAll('button').find((b) => b.text().includes('Cancel'))!.trigger('click')
		await flushPromises()

		// resume() refreshes immediately, so the organizer sees current data
		expect(roundFindings.mock.calls.length).toBeGreaterThan(whilePaused)
		expect(wrapper.text()).not.toContain('Paused while you edit')
	})
})
