// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The notice screen registers people one at a time against the notice the
 * server rendered (0.7). Individual consent, never one tick for the table; a
 * refusal is recorded; a 'required' table continues only once one person has
 * consented, an 'optional' one at once; a server without the notice endpoint
 * gets the table-level text it always showed.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ConsentScreen from '../../frontend/src/recorder/components/ConsentScreen.vue'
import ParticipantsLine from '../../frontend/src/recorder/components/ParticipantsLine.vue'
import { mountWithI18n } from './support/mount'

const consentNotice = vi.fn()
const registerParticipant = vi.fn()

vi.mock('../../frontend/src/recorder/api', () => ({
	recorderApi: {
		consentNotice: (...args: unknown[]) => consentNotice(...args),
		registerParticipant: (...args: unknown[]) => registerParticipant(...args),
	},
}))

const ACCEPT = 'By registering you declare that you have read this notice and you consent to everything in it.'
const NOTICE = {
	version: '2026-10.2', language: 'en', hash: 'a'.repeat(64),
	paragraphs: ['Comune is recording this discussion and is responsible for the data.', ACCEPT],
	acceptance: ACCEPT,
	mode: 'required', participants: [],
}

function registered(name: string, consented: boolean, table: Record<string, unknown>) {
	return {
		participant: { id: 'p1', label: 'P001', name },
		consent: { method: 'TABLE_DEVICE', recording: consented },
		can_record: consented,
		table,
	}
}

beforeEach(() => {
	consentNotice.mockReset()
	registerParticipant.mockReset()
	consentNotice.mockResolvedValue(NOTICE)
})

function mountScreen() {
	return mountWithI18n(ConsentScreen, {
		props: { token: 'tok', handling: { stt_provider: 'vosk' }, tableNumber: 3, colorKey: 'orange' },
	})
}

describe('the notice screen', () => {
	it('shows the server notice and, when required, continues only once someone consents', async () => {
		const wrapper = mountScreen()
		await flushPromises()
		expect(consentNotice).toHaveBeenCalledWith('tok')
		expect(wrapper.find('[data-test="notice"]').text()).toContain('responsible for the data')
		expect(wrapper.text()).toContain('Nobody has registered yet.')
		const cont = wrapper.find('[data-test="continue"]')
		expect(cont.attributes('disabled')).toBeDefined()
		expect(wrapper.text()).toContain('At least one person must register and consent')

		// one person registers
		await wrapper.find('[data-test="add"]').trigger('click')
		expect(wrapper.text()).toContain('Register a participant')
		expect(wrapper.find('[data-test="confirm"]').attributes('disabled')).toBeDefined()
		await wrapper.find('[data-test="name"]').setValue('  Anna ')
		// one box, worded by the notice itself
		expect(wrapper.find('.rc-tick').text()).toBe(ACCEPT)
		expect(wrapper.find('[data-test="confirm"]').attributes('disabled')).toBeDefined()
		await wrapper.find('[data-test="accept"]').setValue(true)
		expect(wrapper.find('[data-test="confirm"]').attributes('disabled')).toBeUndefined()
		registerParticipant.mockResolvedValue(
			registered('Anna', true, { mode: 'required', registered: 1, consenting: 1, can_record: true }),
		)
		await wrapper.find('[data-test="confirm"]').trigger('click')
		await flushPromises()
		// the one acceptance covers every recorded flag
		expect(registerParticipant).toHaveBeenCalledWith('tok', {
			name: 'Anna', email: '', notice_hash: 'a'.repeat(64), notice_read: true,
			recording_consent: true, transcription_consent: true, analysis_consent: true,
			publication_consent: true,
		})
		expect(wrapper.text()).toContain('Participant added')
		expect(wrapper.text()).toContain('Anna')
		expect(wrapper.find('[data-test="continue"]').attributes('disabled')).toBeUndefined()

		// back to the notice: the roster shows her, continue is open
		await wrapper.find('button.rc-btn:not(.rc-primary)').trigger('click') // Add another
		expect(wrapper.text()).toContain('Register a participant')
		await wrapper.findAll('button').find((b) => b.text() === 'Cancel')!.trigger('click')
		expect(wrapper.find('[data-test="roster"]').text()).toContain('Anna')
		expect(wrapper.find('[data-test="roster"]').text()).toContain('Consented')
		await wrapper.find('[data-test="continue"]').trigger('click')
		expect(wrapper.emitted('accept')?.[0]).toEqual([
			{ mode: 'required', registered: 1, consenting: 1, can_record: true },
		])
	})

	it('records a refusal, which opens nothing', async () => {
		const wrapper = mountScreen()
		await flushPromises()
		await wrapper.find('[data-test="add"]').trigger('click')
		await wrapper.find('[data-test="name"]').setValue('Bruno')
		registerParticipant.mockResolvedValue(
			registered('Bruno', false, { mode: 'required', registered: 1, consenting: 0, can_record: false }),
		)
		await wrapper.find('[data-test="refuse"]').trigger('click')
		await flushPromises()
		expect(registerParticipant.mock.calls[0][1]).toMatchObject({
			name: 'Bruno', recording_consent: false, transcription_consent: false, analysis_consent: false,
			publication_consent: false,
		})
		expect(wrapper.text()).toContain('Refusal recorded')
		expect(wrapper.find('[data-test="continue"]').attributes('disabled')).toBeDefined()
	})

	it('continues at once when the assembly only offers registration', async () => {
		consentNotice.mockResolvedValue({ ...NOTICE, mode: 'optional' })
		const wrapper = mountScreen()
		await flushPromises()
		expect(wrapper.find('[data-test="continue"]').attributes('disabled')).toBeUndefined()
		await wrapper.find('[data-test="continue"]').trigger('click')
		expect(wrapper.emitted('accept')?.[0]).toEqual([null])
	})

	it('falls back to the table-level text on a server without the notice', async () => {
		consentNotice.mockRejectedValue(new Error('HTTP 404'))
		const wrapper = mountScreen()
		await flushPromises()
		expect(wrapper.text()).toContain('This phone records the conversation at your table.')
		const agree = wrapper.find('button.rc-primary')
		expect(agree.text()).toBe('Everyone at this table agrees — continue')
		await agree.trigger('click')
		expect(wrapper.emitted('accept')).toBeTruthy()
	})
})

describe('the participants line', () => {
	it('says how many registered, or that a required table cannot record yet', () => {
		const some = mountWithI18n(ParticipantsLine, {
			props: { consent: { mode: 'optional', registered: 3, consenting: 3, can_record: true } },
		})
		expect(some.text()).toBe('Participants: 3 · Add')
		const none = mountWithI18n(ParticipantsLine, {
			props: { consent: { mode: 'optional', registered: 0, consenting: 0, can_record: true } },
		})
		expect(none.text()).toBe('No participants registered · Add')
		const blocked = mountWithI18n(ParticipantsLine, {
			props: { consent: { mode: 'required', registered: 1, consenting: 0, can_record: false } },
		})
		expect(blocked.text()).toBe('Register a participant before recording')
		expect(blocked.find('button').classes()).toContain('rc-participants--blocked')
		expect(mountWithI18n(ParticipantsLine, { props: { consent: undefined } }).find('button').exists()).toBe(false)
	})
})
