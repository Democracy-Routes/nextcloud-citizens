// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The Participants tab shows the consent act recorded at the table (0.7):
 * consented or refused, where and how the person registered — and a dash
 * for a person from the organizer's own list.
 */
import { flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import ParticipantsTab from '../../frontend/src/components/ParticipantsTab.vue'
import { mountWithI18n } from './support/mount'

// hoisted with vi.mock: a plain const would be read before initialisation
const { CONSENT } = vi.hoisted(() => ({
	CONSENT: {
		method: 'TABLE_DEVICE', notice_version: '2026-10', notice_hash: 'a'.repeat(64), notice_language: 'en',
		notice_read: true, recording: true, transcription: true, analysis: true, publication: false,
		confirmed_at: '2026-10-05T10:00:00Z', withdrawn_at: null,
	},
}))

const participantConsent = vi.fn()
const participantMoved = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: {
		listParticipants: vi.fn().mockResolvedValue([
			{ id: '1', label: 'P001', name: 'Anna', email: '', notes: '', source: 'TABLE_DEVICE',
				registered_table_number: 3, consent: CONSENT },
			{ id: '2', label: 'P002', name: 'Bruno', email: '', notes: '', source: 'SELF_PHONE',
				registered_table_number: 3, consent: { ...CONSENT, method: 'SELF_PHONE', recording: false } },
			{ id: '3', label: 'P003', name: '', email: '', notes: '', source: 'ORGANIZER',
				registered_table_number: null, consent: null },
		]),
		addParticipants: vi.fn(),
		importCsv: vi.fn(),
		deleteParticipant: vi.fn(),
		participantConsent: (...args: unknown[]) => participantConsent(...args),
		participantMoved: (...args: unknown[]) => participantMoved(...args),
		registrationLink: vi.fn().mockResolvedValue({
			url: 'https://nc.example/recorder.html#/register/pre', qr_svg: '<svg xmlns="http://www.w3.org/2000/svg"></svg>',
			expires_at: '2026-11-05T00:00:00Z', registered: { total: 4, seated: 1 },
		}),
	},
	ApiError: class extends Error {},
	BASE: '',
}))

describe('the Participants tab', () => {
	it('shows each person\'s consent, where and how they registered', async () => {
		const wrapper = mountWithI18n(ParticipantsTab, { props: { assemblyId: 'a1' } })
		await flushPromises()
		const cells = wrapper.findAll('td.cz-consent').map((td) => td.text().replace(/\s+/g, ' ').trim())
		expect(cells).toEqual([
			'✓ consented · Table 3 (table phone)',
			'✗ refused · Table 3 (own phone)',
			'—',
		])
		expect(wrapper.findAll('td.cz-consent')[0].attributes('title')).toContain('recording yes')
		expect(wrapper.findAll('td.cz-consent')[0].attributes('title')).toContain('notice 2026-10')
		// the pre-registration link, with how many used it
		const card = wrapper.find('[data-test="registration-link"]')
		expect(card.text()).toContain('https://nc.example/recorder.html#/register/pre')
		expect(card.text()).toContain('4 registered ahead · 1 seated.')
	})

	it('records a change of mind, a withdrawal and a move, each after a confirm', async () => {
		participantConsent.mockReset().mockResolvedValue({ participant: { id: '2', label: 'P002' }, consent: {} })
		participantMoved.mockReset().mockResolvedValue({ participant: { id: '1', label: 'P001' } })
		const wrapper = mountWithI18n(ParticipantsTab, { props: { assemblyId: 'a1' } })
		await flushPromises()
		const rows = wrapper.findAll('tbody tr')
		// Anna consented: she can withdraw or be moved; Bruno refused: change of mind or moved
		expect(rows[0].findAll('[data-test^="consent-"]').map((b) => b.text())).toEqual(['Withdraws consent', 'Moved to another table'])
		expect(rows[1].findAll('[data-test^="consent-"]').map((b) => b.text())).toEqual(['Changed their mind', 'Moved to another table'])
		expect(rows[2].findAll('[data-test^="consent-"]')).toHaveLength(0)

		await rows[1].find('[data-test="consent-change"]').trigger('click')
		expect(wrapper.text()).toContain('changed their mind?')
		await wrapper.findAll('button').find((b) => b.text() === 'Record the consent')!.trigger('click')
		await flushPromises()
		expect(participantConsent).toHaveBeenCalledWith('a1', '2', {
			recording_consent: true, transcription_consent: true, analysis_consent: true, publication_consent: true,
		})

		await rows[0].find('[data-test="consent-withdraw"]').trigger('click')
		expect(wrapper.text()).toContain('withdraws consent?')
		await wrapper.findAll('button').find((b) => b.text() === 'Record the withdrawal')!.trigger('click')
		await flushPromises()
		expect(participantConsent).toHaveBeenLastCalledWith('a1', '1', {
			recording_consent: false, transcription_consent: false, analysis_consent: false, publication_consent: false,
		})

		await rows[0].find('[data-test="consent-move"]').trigger('click')
		await wrapper.findAll('button').find((b) => b.text() === 'Mark as moved')!.trigger('click')
		await flushPromises()
		expect(participantMoved).toHaveBeenCalledWith('a1', '1')
	})

})
