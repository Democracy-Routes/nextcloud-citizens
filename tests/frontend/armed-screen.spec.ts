// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * A microphone failure must not become an infinite loop.
 *
 * ArmedScreen auto-starts whatever round is ACTIVE. When the recording screen
 * failed to open the microphone it offered only "Back", which returned here —
 * where the next poll, five seconds later, saw the same ACTIVE round and sent
 * the table straight back in. The table could not escape, and nothing on
 * screen explained why it kept flickering.
 */
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ArmedScreen from '../../frontend/src/recorder/components/ArmedScreen.vue'

const status = vi.fn()
const heartbeat = vi.fn().mockResolvedValue(undefined)

vi.mock('../../frontend/src/recorder/api', () => ({
	recorderApi: {
		status: (...args: unknown[]) => status(...args),
		heartbeat: (...args: unknown[]) => heartbeat(...args),
	},
	RecorderApiError: class extends Error {},
}))

const ACTIVE_ROUND = {
	id: 'round-1',
	position: 1,
	title: 'Mobility',
	question: 'What should change?',
	duration_minutes: 30,
	status: 'ACTIVE',
	recorded_state: null,
}

const SESSION = {
	session_token: 'tok',
	table_number: 3,
	assembly: { id: 'a1', name: 'Bologna', language: 'it', recording_mode: 'orchestrated' },
	rounds: [ACTIVE_ROUND],
}

beforeEach(() => {
	status.mockReset()
	status.mockResolvedValue({ rounds: [ACTIVE_ROUND], report_available: false })
})

describe('ArmedScreen auto-start', () => {
	it('starts the active round when nothing is wrong', async () => {
		const wrapper = mount(ArmedScreen, { props: { session: SESSION } })
		await flushPromises()
		expect(wrapper.emitted('start')).toBeTruthy()
	})

	it('does NOT auto-start a round whose microphone just failed', async () => {
		const wrapper = mount(ArmedScreen, {
			props: { session: SESSION, blockedRoundId: 'round-1' },
		})
		await flushPromises()

		expect(wrapper.emitted('start')).toBeFalsy()
		expect(wrapper.text()).toContain('Microphone unavailable')
	})

	it('starts again only when the table explicitly asks', async () => {
		const wrapper = mount(ArmedScreen, {
			props: { session: SESSION, blockedRoundId: 'round-1' },
		})
		await flushPromises()
		expect(wrapper.emitted('start')).toBeFalsy()

		await wrapper.find('button.rc-primary').trigger('click')

		expect(wrapper.emitted('start')?.[0]).toEqual([ACTIVE_ROUND])
	})

	it('still auto-starts a DIFFERENT round while one is blocked', async () => {
		const other = { ...ACTIVE_ROUND, id: 'round-2', position: 2 }
		status.mockResolvedValue({ rounds: [other], report_available: false })
		const wrapper = mount(ArmedScreen, {
			props: { session: SESSION, blockedRoundId: 'round-1' },
		})
		await flushPromises()
		expect(wrapper.emitted('start')?.[0]).toEqual([other])
	})
})
