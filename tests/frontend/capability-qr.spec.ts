// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The phone that already joined decides what the next code means, and the
 * card says so above the QR: ADD RECORDER for this table, or ADD NEW TABLE.
 * The code is rendered as an image, never injected markup; an expired code
 * offers a fresh one; a server refusal is said honestly.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CapabilityQr from '../../frontend/src/recorder/components/CapabilityQr.vue'
import TableActions from '../../frontend/src/recorder/components/TableActions.vue'
import { mountWithI18n } from './support/mount'

const createCapability = vi.fn()

vi.mock('../../frontend/src/recorder/api', () => ({
	recorderApi: { createCapability: (...a: unknown[]) => createCapability(...a) },
	RecorderApiError: class extends Error {},
}))

function card(purpose: string, minutes = 15) {
	return {
		purpose,
		url: 'https://nc.example/recorder.html#/join/tok',
		qr_svg: '<svg xmlns="http://www.w3.org/2000/svg"></svg>',
		expires_at: new Date(Date.now() + minutes * 60_000).toISOString(),
		table_number: purpose === 'ADD_TABLE' ? null : 7,
		color_key: purpose === 'ADD_TABLE' ? null : 'blue',
		round_id: 'r1',
	}
}

beforeEach(() => {
	createCapability.mockReset()
})

describe('the capability card', () => {
	it('asks the server for the chosen intent and shows it above the code', async () => {
		createCapability.mockResolvedValue(card('ADD_RECORDER_TO_TABLE'))
		const wrapper = mountWithI18n(CapabilityQr, {
			props: { token: 'tok', purpose: 'ADD_RECORDER_TO_TABLE', tableNumber: 7, colorKey: 'blue', roundId: 'r1' },
		})
		await flushPromises()

		expect(createCapability).toHaveBeenCalledWith('tok', 'ADD_RECORDER_TO_TABLE', 'r1')
		expect(wrapper.find('.rc-eyebrow').text()).toBe('ADD RECORDER')
		expect(wrapper.find('.rc-table-badge').text().replace(/\s+/g, ' ')).toBe('TABLE 7 · BLUE')
		expect(wrapper.find('img.rc-qr').attributes('src')).toMatch(/^data:image\/svg\+xml;base64,/)
		expect(wrapper.text()).toContain('records this table too')
		expect(wrapper.text()).toContain('15 more minutes')
	})

	it('names a new table as the intent, with no table badge', async () => {
		createCapability.mockResolvedValue(card('ADD_TABLE'))
		const wrapper = mountWithI18n(CapabilityQr, {
			props: { token: 'tok', purpose: 'ADD_TABLE', tableNumber: 7, colorKey: 'blue' },
		})
		await flushPromises()

		expect(createCapability).toHaveBeenCalledWith('tok', 'ADD_TABLE', undefined)
		expect(wrapper.find('.rc-eyebrow').text()).toBe('ADD NEW TABLE')
		expect(wrapper.find('.rc-table-badge').exists()).toBe(false)
		expect(wrapper.text()).toContain('recorder of the next table')
	})

	it('offers a fresh code once this one has expired', async () => {
		createCapability.mockResolvedValue(card('ADD_TABLE', -1))
		const wrapper = mountWithI18n(CapabilityQr, {
			props: { token: 'tok', purpose: 'ADD_TABLE', tableNumber: 7 },
		})
		await flushPromises()

		expect(wrapper.find('img').exists()).toBe(false)
		expect(wrapper.text()).toContain('expired')
		createCapability.mockResolvedValue(card('ADD_TABLE'))
		await wrapper.findAll('button').find((b) => b.text().includes('Make a new code'))!.trigger('click')
		await flushPromises()
		expect(createCapability).toHaveBeenCalledTimes(2)
		expect(wrapper.find('img.rc-qr').exists()).toBe(true)
	})

	it('says so when the server will not make the code, and can be closed', async () => {
		createCapability.mockRejectedValue(new Error('HTTP 409'))
		const wrapper = mountWithI18n(CapabilityQr, {
			props: { token: 'tok', purpose: 'ADD_TABLE', tableNumber: 7 },
		})
		await flushPromises()

		expect(wrapper.text()).toContain('ask the organizer')
		await wrapper.findAll('button').find((b) => b.text().includes('Close'))!.trigger('click')
		expect(wrapper.emitted('close')).toBeTruthy()
	})
})

describe('the table actions', () => {
	const session = {
		session_token: 'tok',
		table_number: 7,
		table_color: 'blue',
		assembly: { id: 'a1', name: 'Milan', language: 'en', recording_mode: 'orchestrated' },
		rounds: [],
	}

	it('offers both actions and opens the chosen code', async () => {
		createCapability.mockResolvedValue(card('ADD_RECORDER_TO_TABLE'))
		const wrapper = mountWithI18n(TableActions, { props: { session, roundId: 'r1' } })
		const labels = wrapper.findAll('.rc-table-actions__row button').map((b) => b.text())
		expect(labels).toEqual(['Add new Table', 'Add Recorder to this Table'])
		expect(wrapper.find('.rc-capability').exists()).toBe(false)

		await wrapper.findAll('.rc-table-actions__row button')[1].trigger('click')
		await flushPromises()
		expect(createCapability).toHaveBeenCalledWith('tok', 'ADD_RECORDER_TO_TABLE', 'r1')
		expect(wrapper.find('.rc-capability .rc-eyebrow').text()).toBe('ADD RECORDER')

		// the same button again closes it
		await wrapper.findAll('.rc-table-actions__row button')[1].trigger('click')
		expect(wrapper.find('.rc-capability').exists()).toBe(false)
	})

	it('is absent in a plenary room, which has its one shared code', () => {
		const plenary = { ...session, assembly: { ...session.assembly, recording_mode: 'plenary' } }
		const wrapper = mountWithI18n(TableActions, { props: { session: plenary } })
		expect(wrapper.find('.rc-table-actions').exists()).toBe(false)
	})
})
