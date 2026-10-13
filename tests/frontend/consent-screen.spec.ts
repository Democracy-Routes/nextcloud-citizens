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
const searchParticipants = vi.fn()
const seatParticipant = vi.fn()
const changeConsent = vi.fn()
const markMoved = vi.fn()
const changeLanguage = vi.fn()

vi.mock('../../frontend/src/recorder/api', () => ({
	recorderApi: {
		consentNotice: (...args: unknown[]) => consentNotice(...args),
		registerParticipant: (...args: unknown[]) => registerParticipant(...args),
		searchParticipants: (...args: unknown[]) => searchParticipants(...args),
		seatParticipant: (...args: unknown[]) => seatParticipant(...args),
		changeConsent: (...args: unknown[]) => changeConsent(...args),
		markMoved: (...args: unknown[]) => markMoved(...args),
		changeLanguage: (...args: unknown[]) => changeLanguage(...args),
	},
	RecorderApiError: class extends Error {},
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

	it('finds a person who registered ahead and seats them here', async () => {
		vi.useFakeTimers()
		searchParticipants.mockResolvedValue([{ id: 'p9', label: 'P009', name: 'Ines Rossi', recording_consent: true }])
		seatParticipant.mockResolvedValue({
			participant: { id: 'p9', label: 'P009', name: 'Ines Rossi' },
			table: { mode: 'required', registered: 1, consenting: 1, can_record: true },
		})
		const wrapper = mountScreen()
		await flushPromises()
		await wrapper.find('[data-test="find"]').trigger('click')
		await wrapper.find('[data-test="find-input"]').setValue('ros')
		vi.advanceTimersByTime(300)
		await flushPromises()
		expect(searchParticipants).toHaveBeenCalledWith('tok', 'ros')
		expect(wrapper.find('[data-test="matches"]').text()).toContain('Ines Rossi')
		consentNotice.mockResolvedValue({
			...NOTICE, participants: [{ label: 'P009', name: 'Ines Rossi', recording_consent: true }],
		})
		await wrapper.find('[data-test="seat-p9"]').trigger('click')
		await flushPromises()
		expect(seatParticipant).toHaveBeenCalledWith('tok', 'p9')
		expect(wrapper.find('[data-test="roster"]').text()).toContain('Ines Rossi')
		expect(wrapper.find('[data-test="continue"]').attributes('disabled')).toBeUndefined()
		vi.useRealTimers()
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

describe('the scroll-gated accept, deny, language switch and joined line (0.8)', () => {
	/** happy-dom defaults every layout metric to 0, where "fits already" is
	 * trivially true — these tests set real ones so the gate has something to
	 * gate on. */
	function setFrame(
		frame: { element: Element },
		opts: { scrollTop: number; clientHeight: number; scrollHeight: number },
	) {
		const el = frame.element as HTMLElement
		Object.defineProperty(el, 'scrollTop', { value: opts.scrollTop, configurable: true })
		Object.defineProperty(el, 'clientHeight', { value: opts.clientHeight, configurable: true })
		Object.defineProperty(el, 'scrollHeight', { value: opts.scrollHeight, configurable: true })
	}

	it('keeps Accept disabled until the notice is scrolled to its end', async () => {
		consentNotice.mockResolvedValue({ ...NOTICE, mode: 'optional' }) // isolate the scroll gate from the roster gate
		const wrapper = mountScreen()
		await flushPromises()
		const frame = wrapper.find('[data-test="notice-frame"]')
		setFrame(frame, { scrollTop: 0, clientHeight: 100, scrollHeight: 500 })
		await frame.trigger('scroll')
		expect(wrapper.find('[data-test="continue"]').attributes('disabled')).toBeDefined()
		expect(wrapper.find('[data-test="scroll-hint"]').exists()).toBe(true)

		setFrame(frame, { scrollTop: 400, clientHeight: 100, scrollHeight: 500 })
		await frame.trigger('scroll')
		expect(wrapper.find('[data-test="continue"]').attributes('disabled')).toBeUndefined()
		expect(wrapper.find('[data-test="scroll-hint"]').exists()).toBe(false)
	})

	it('denies without contacting the server', async () => {
		const wrapper = mountScreen()
		await flushPromises()
		await wrapper.find('[data-test="deny"]').trigger('click')
		expect(wrapper.emitted('deny')).toBeTruthy()
		expect(registerParticipant).not.toHaveBeenCalled()
	})

	it('shows a language switch only for a Record-now Session that can still change it, and re-fetches on change', async () => {
		const assembly = {
			id: 'a1', kind: 'session', name: 'Session', language: 'en',
			recording_mode: 'independent', language_changeable: true,
		}
		consentNotice.mockReset()
		consentNotice.mockResolvedValueOnce(NOTICE).mockResolvedValueOnce({ ...NOTICE, language: 'it' })
		changeLanguage.mockReset().mockResolvedValue({ language: 'it' })
		const wrapper = mountWithI18n(ConsentScreen, {
			props: { token: 'tok', handling: null, tableNumber: 3, colorKey: 'orange', assembly },
		})
		await flushPromises()
		expect(wrapper.find('[data-test="language"]').exists()).toBe(true)
		await wrapper.find('[data-test="language"]').setValue('it')
		await flushPromises()
		expect(changeLanguage).toHaveBeenCalledWith('tok', 'it')
		expect(consentNotice).toHaveBeenCalledTimes(2)
	})

	it('does not offer the language switch outside a Record-now Session', async () => {
		const wrapper = mountScreen()
		await flushPromises()
		expect(wrapper.find('[data-test="language"]').exists()).toBe(false)
	})

	it('reverts the language and shows the server message when the switch is refused', async () => {
		const assembly = {
			id: 'a1', kind: 'session', name: 'Session', language: 'en',
			recording_mode: 'independent', language_changeable: true,
		}
		consentNotice.mockResolvedValue(NOTICE)
		changeLanguage.mockReset().mockRejectedValue(new Error('This table has already started recording.'))
		const wrapper = mountWithI18n(ConsentScreen, {
			props: { token: 'tok', handling: null, tableNumber: 3, colorKey: 'orange', assembly },
		})
		await flushPromises()
		await wrapper.find('[data-test="language"]').setValue('it')
		await flushPromises()
		expect(wrapper.text()).toContain('This table has already started recording.')
		expect((wrapper.find('[data-test="language"]').element as HTMLSelectElement).value).toBe('en')
	})

	it('shows the joined line above the notice when a scanned code decided this table', async () => {
		consentNotice.mockResolvedValue(NOTICE)
		const wrapper = mountWithI18n(ConsentScreen, {
			props: {
				token: 'tok', handling: null, tableNumber: 9, colorKey: 'blue',
				pendingJoined: { purpose: 'ADD_TABLE', table_number: 9, color_key: 'blue', slot: 1, table_created: true },
			},
		})
		await flushPromises()
		expect(wrapper.find('[data-test="joined-line"]').text()).toBe('This phone is the recorder of the new table')
	})

	it('relays a newly-scanned code without the full notice once this device already consented', async () => {
		const wrapper = mountWithI18n(ConsentScreen, {
			props: {
				token: 'tok', handling: null, tableNumber: 2, colorKey: 'green', alreadyConsented: true,
				pendingJoined: { purpose: 'ADD_RECORDER_TO_TABLE', table_number: 2, color_key: 'green', slot: 2, table_created: false },
			},
		})
		await flushPromises()
		expect(consentNotice).not.toHaveBeenCalled()
		expect(wrapper.find('[data-test="joined-line"]').text()).toBe('You join as Recorder B')
		await wrapper.find('[data-test="continue"]').trigger('click')
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

	it('offers the roster its actions: moved, changed their mind, withdraws', async () => {
		changeConsent.mockReset()
		markMoved.mockReset()
		const anna = { id: 'p1', label: 'P001', name: 'Anna', recording_consent: true, publication_consent: false, refused: false }
		const bruno = { id: 'p2', label: 'P002', name: 'Bruno', recording_consent: false, publication_consent: false, refused: true }
		consentNotice.mockResolvedValue({ ...NOTICE, participants: [anna, bruno] })
		const wrapper = mountScreen()
		await flushPromises()
		// a refusal seated here blocks Continue, and says what to do
		expect(wrapper.find('[data-test="continue"]').attributes('disabled')).toBeDefined()
		expect(wrapper.find('[data-test="refused-hint"]').text()).toContain('Mark them as moved')
		expect(wrapper.find('[data-test="roster"]').text()).toContain('no quotations')

		// Bruno is moved to a table that is not recorded
		markMoved.mockResolvedValue({ participant: { id: 'p2', label: 'P002', name: 'Bruno' }, table: { mode: 'required', registered: 1, consenting: 1, refusing: 0, can_record: true } })
		consentNotice.mockResolvedValue({ ...NOTICE, participants: [anna] })
		await wrapper.find('[data-test="moved"]').trigger('click')
		await flushPromises()
		expect(markMoved).toHaveBeenCalledWith('tok', 'p2')
		expect(wrapper.find('[data-test="refused-hint"]').exists()).toBe(false)
		expect(wrapper.find('[data-test="continue"]').attributes('disabled')).toBeUndefined()

		// Anna withdraws: a confirm first, then every flag false
		await wrapper.find('[data-test="withdraw"]').trigger('click')
		expect(wrapper.find('[data-test="withdraw-confirm"]').text()).toContain('Anna withdraws consent')
		changeConsent.mockResolvedValue({ participant: { id: 'p1', label: 'P001', name: 'Anna' }, table: { mode: 'required', registered: 1, consenting: 0, refusing: 1, can_record: false } })
		consentNotice.mockResolvedValue({ ...NOTICE, participants: [{ ...anna, recording_consent: false, refused: true }] })
		await wrapper.find('[data-test="withdraw-yes"]').trigger('click')
		await flushPromises()
		expect(changeConsent).toHaveBeenCalledWith('tok', 'p1', {
			notice_hash: 'a'.repeat(64), notice_read: true, recording_consent: false,
			transcription_consent: false, analysis_consent: false, publication_consent: false,
		})
		expect(wrapper.find('[data-test="continue"]').attributes('disabled')).toBeDefined()

		// ...and changes her mind: the form with her name fixed, then a new act
		await wrapper.find('[data-test="changed-mind"]').trigger('click')
		expect(wrapper.text()).toContain('Anna changed their mind')
		expect(wrapper.find('[data-test="refuse"]').exists()).toBe(false)
		await wrapper.find('[data-test="accept"]').setValue(true)
		await wrapper.find('[data-test="quotations"]').setValue(false)
		consentNotice.mockResolvedValue({ ...NOTICE, participants: [anna] })
		await wrapper.find('[data-test="confirm"]').trigger('click')
		await flushPromises()
		expect(changeConsent).toHaveBeenLastCalledWith('tok', 'p1', {
			notice_hash: 'a'.repeat(64), notice_read: true, recording_consent: true,
			transcription_consent: true, analysis_consent: true, publication_consent: false,
		})
		expect(wrapper.find('[data-test="roster"]').text()).toContain('Anna')
	})

	it('says on the participants line that someone who refused is at the table', () => {
		const blocked = mountWithI18n(ParticipantsLine, {
			props: { consent: { mode: 'required', registered: 2, consenting: 1, refusing: 1, can_record: false } },
		})
		expect(blocked.text()).toContain('Someone who refused is at this table')
	})
})
