// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The one bottom bar every table screen ends with: New table on the left, the
 * screen's primary action in the middle, Add recorder on the right — the same
 * on preflight, armed, recording and done, so people learn it once. A side
 * button opens the intent-carrying QR in a sheet over the screen.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import TableBar from '../../frontend/src/recorder/components/TableBar.vue'
import { mountWithI18n } from './support/mount'

const createCapability = vi.fn()

vi.mock('../../frontend/src/recorder/api', () => ({
	recorderApi: { createCapability: (...a: unknown[]) => createCapability(...a) },
	RecorderApiError: class extends Error {},
}))

const session = {
	session_token: 'tok',
	table_number: 7,
	table_color: 'blue',
	assembly: { id: 'a1', name: 'Milan', language: 'en', recording_mode: 'orchestrated' },
	rounds: [],
}

beforeEach(() => {
	createCapability.mockReset().mockResolvedValue({
		purpose: 'ADD_RECORDER_TO_TABLE', url: 'https://nc.example/recorder.html#/join/tok',
		qr_svg: '<svg xmlns="http://www.w3.org/2000/svg"></svg>',
		expires_at: new Date(Date.now() + 15 * 60_000).toISOString(),
		table_number: 7, color_key: 'blue', round_id: 'r1',
	})
})

function mountBar(mode = 'orchestrated', quiet = false) {
	return mountWithI18n(TableBar, {
		props: { session: { ...session, assembly: { ...session.assembly, recording_mode: mode } }, roundId: 'r1', quiet },
		slots: { default: '<button class="rc-btn rc-primary">READY</button>' },
	})
}

describe('the table bar', () => {
	it('is New table | primary action | Add recorder, in that order', () => {
		const wrapper = mountBar()
		const bar = wrapper.find('.rc-bar')
		const children = bar.element.children
		expect(children[0].className).toContain('rc-bar__side')
		expect(children[0].textContent).toContain('New table')
		expect(children[1].className).toContain('rc-bar__main')
		expect(children[1].textContent).toContain('READY')
		expect(children[2].className).toContain('rc-bar__side')
		expect(children[2].textContent).toContain('Add recorder')
		expect(wrapper.find('.rc-sheet').exists()).toBe(false)
	})

	it('opens the chosen code in a sheet and closes it again', async () => {
		const wrapper = mountBar()
		await wrapper.findAll('.rc-bar__side')[1].trigger('click')
		await flushPromises()

		expect(createCapability).toHaveBeenCalledWith('tok', 'ADD_RECORDER_TO_TABLE', 'r1')
		expect(wrapper.find('.rc-sheet .rc-eyebrow').text()).toBe('ADD RECORDER')
		expect(wrapper.findAll('.rc-bar__side')[1].classes()).toContain('rc-bar__side--open')

		await wrapper.find('.rc-sheet').findAll('button').find((b) => b.text() === 'Close')!.trigger('click')
		expect(wrapper.find('.rc-sheet').exists()).toBe(false)

		// tapping the scrim closes too
		await wrapper.findAll('.rc-bar__side')[0].trigger('click')
		await flushPromises()
		expect(wrapper.find('.rc-sheet .rc-eyebrow').text()).toBe('ADD NEW TABLE')
		await wrapper.find('.rc-sheet-scrim').trigger('click')
		expect(wrapper.find('.rc-sheet').exists()).toBe(false)
	})

	it('steps the side buttons back while recording', () => {
		expect(mountBar('orchestrated', true).find('.rc-bar').classes()).toContain('rc-bar--quiet')
	})

	it('keeps only the primary action in a plenary room', () => {
		const wrapper = mountBar('plenary')
		expect(wrapper.findAll('.rc-bar__side')).toHaveLength(0)
		expect(wrapper.find('.rc-bar').classes()).toContain('rc-bar--plain')
		expect(wrapper.text()).toContain('READY')
	})
})
