// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * A standalone Session grows into an Assembly the moment a second session is
 * wanted: the Sessions tab asks for the event's name, promotes the container
 * and adds the session. An assembly keeps its plain "Add session".
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import RoundsTab from '../../frontend/src/components/RoundsTab.vue'
import { mountWithI18n } from './support/mount'

const promoteSession = vi.fn()
const addRound = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: {
		promoteSession: (...a: unknown[]) => promoteSession(...a),
		addRound: (...a: unknown[]) => addRound(...a),
	},
	ApiError: class extends Error {
		status = 0
	},
	BASE: '',
}))

const round = {
	id: 'r1', position: 1, title: '', question: 'How should mobility improve?', objective: null,
	duration_minutes: 30, status: 'NOT_STARTED', started_at: null, ended_at: null, recording_count: 0,
}

function assembly(kind: 'session' | 'assembly') {
	return {
		id: 'c1', kind, name: 'How should mobility improve?', description: '', language: 'en',
		scheduled_at: null, status: 'DRAFT', recording_mode: 'orchestrated', expected_participants: 0,
		default_table_count: 2, analysis_instructions: '', auto_purge_device_audio: true, redact_names: '',
		closed_at: null, created_by: 'me', created_at: '2026-10-05T10:00:00Z', rounds: [round],
		participant_count: 0,
	}
}

beforeEach(() => {
	promoteSession.mockReset().mockResolvedValue({ container_id: 'c1', kind: 'assembly', name: 'Milan Mobility' })
	addRound.mockReset().mockResolvedValue({ ...round, id: 'r2', position: 2 })
})

describe('adding a second session', () => {
	it('on a Session asks for the event name, promotes it and adds the session', async () => {
		const wrapper = mountWithI18n(RoundsTab, { props: { assembly: assembly('session') } })
		const add = wrapper.findAll('button').find((b) => b.text() === 'Add another session')!
		await add.trigger('click')
		expect(wrapper.text()).toContain('this becomes an Assembly')

		await wrapper.find('#cz-event-name').setValue('Milan Mobility')
		await wrapper.findAll('button').find((b) => b.text().includes('Make it an Assembly'))!.trigger('click')
		await flushPromises()

		expect(promoteSession).toHaveBeenCalledWith('r1', 'Milan Mobility')
		expect(addRound).toHaveBeenCalledWith('c1', { title: 'Round 2', question: '', duration_minutes: 30 })
		expect(wrapper.emitted('changed')).toBeTruthy()
	})

	it('on an Assembly simply adds the session', async () => {
		const wrapper = mountWithI18n(RoundsTab, { props: { assembly: assembly('assembly') } })
		expect(wrapper.findAll('button').some((b) => b.text() === 'Add another session')).toBe(false)
		await wrapper.findAll('button').find((b) => b.text() === 'Add session')!.trigger('click')
		await flushPromises()

		expect(promoteSession).not.toHaveBeenCalled()
		expect(addRound).toHaveBeenCalledTimes(1)
	})
})
