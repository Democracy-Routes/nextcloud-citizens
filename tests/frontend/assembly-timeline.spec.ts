// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The event at a glance above the Plan / Run / Results spaces (0.7): the
 * sessions as pills with their state, the live one highlighted, the headline
 * counts; a click opens the Run space on that session.
 */
import { describe, expect, it } from 'vitest'
import AssemblyTimeline from '../../frontend/src/components/AssemblyTimeline.vue'
import { mountWithI18n } from './support/mount'

const ASSEMBLY = {
	id: 'a1',
	kind: 'assembly',
	name: 'Bologna',
	description: '',
	language: 'it',
	scheduled_at: null,
	status: 'ACTIVE',
	recording_mode: 'orchestrated',
	expected_participants: 40,
	participant_count: 31,
	default_table_count: 5,
	analysis_instructions: '',
	auto_purge_device_audio: true,
	redact_names: '',
	closed_at: null,
	created_by: 'u',
	created_at: 'now',
	rounds: [
		{ id: 'r2', position: 2, title: 'Proposals', question: 'Q2', duration_minutes: 20, status: 'NOT_STARTED', started_at: null, ended_at: null },
		{ id: 'r1', position: 1, title: 'Problems', question: 'Q1', duration_minutes: 20, status: 'ACTIVE', started_at: 'now', ended_at: null },
	],
}

describe('the assembly timeline', () => {
	it('shows the headline counts and the sessions in order, the live one marked', () => {
		const wrapper = mountWithI18n(AssemblyTimeline, { props: { assembly: ASSEMBLY } })
		expect(wrapper.find('[data-test="headline"]').text()).toContain('31 of 40 participants')
		expect(wrapper.find('[data-test="headline"]').text()).toContain('5 tables')
		expect(wrapper.find('[data-test="headline"]').text()).toContain('2 sessions')
		const pills = wrapper.findAll('.cz-timeline__pill')
		expect(pills.map((p) => p.find('.cz-timeline__title').text())).toEqual(['Problems', 'Proposals'])
		expect(pills[0].classes()).toContain('cz-timeline__pill--live')
		expect(pills[0].text()).toContain('Live now')
		expect(pills[1].text()).toContain('Not started')
	})

	it('opens the Run space on the session that was clicked', async () => {
		const wrapper = mountWithI18n(AssemblyTimeline, { props: { assembly: ASSEMBLY } })
		await wrapper.find('[data-test="timeline-2"]').trigger('click')
		expect(wrapper.emitted('open')?.[0]).toEqual(['r2'])
	})

	it('describes a whole-room session without a participant target', () => {
		const wrapper = mountWithI18n(AssemblyTimeline, {
			props: {
				assembly: {
					...ASSEMBLY, kind: 'session', recording_mode: 'plenary', expected_participants: 0,
					closed_at: '2026-10-06T10:00:00Z',
					rounds: [ASSEMBLY.rounds[1]],
				},
			},
		})
		const headline = wrapper.find('[data-test="headline"]').text()
		expect(headline).toContain('Whole room')
		expect(headline).toContain('1 session')
		expect(headline).not.toContain('participants')
		expect(headline).toContain('Closed')
	})
})
