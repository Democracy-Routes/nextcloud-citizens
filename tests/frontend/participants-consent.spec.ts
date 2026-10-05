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
	})
})
