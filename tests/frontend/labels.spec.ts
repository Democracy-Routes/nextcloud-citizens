// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * How a session is named on screen, mirroring round_heading() on the server,
 * and the noun the Report tab closes and reopens — an organized assembly or
 * a standalone Session — in both spellings.
 */
import { beforeEach, describe, expect, it } from 'vitest'
import { i18n } from '../../frontend/src/i18n'
import { installOrganizerCatalogue } from '../../frontend/src/i18n/organizer'
import { kindNoun, roundHeading } from '../../frontend/src/labels'

beforeEach(() => {
	installOrganizerCatalogue()
	i18n.global.locale.value = 'en'
})

describe('roundHeading', () => {
	it('uses the plain heading for every pre-filled spelling, old and new', () => {
		expect(roundHeading(2, 'Session 2')).toBe('Session 2')
		expect(roundHeading(2, 'Round 2')).toBe('Session 2')
		expect(roundHeading(2, 'round 2')).toBe('Session 2')
		expect(roundHeading(4, '')).toBe('Session 4')
	})

	it('keeps a title that already opens with the number, and prefixes one that does not', () => {
		expect(roundHeading(1, 'Session 1 - design')).toBe('Session 1 - design')
		expect(roundHeading(1, 'Round 1 - design')).toBe('Round 1 - design')
		expect(roundHeading(1, '1. Problems')).toBe('1. Problems')
		expect(roundHeading(3, 'Mobility')).toBe('Session 3 — Mobility')
		expect(roundHeading(1, 'Round 2 - design')).toBe('Session 1 — Round 2 - design')
	})

	it('follows the UI language', () => {
		i18n.global.locale.value = 'it'
		expect(roundHeading(2, 'Session 2')).toBe('Sessione 2')
		expect(roundHeading(2, 'Turno 2')).toBe('Sessione 2')
		expect(roundHeading(3, 'Mobilità')).toBe('Sessione 3 — Mobilità')
	})
})

describe('kindNoun', () => {
	it('names the assembly or the Session, with the article, in both spellings', () => {
		expect(kindNoun('assembly')).toEqual({ thing: 'the assembly', Thing: 'The assembly' })
		expect(kindNoun('session')).toEqual({ thing: 'the Session', Thing: 'The Session' })
		expect(kindNoun(undefined)).toEqual({ thing: 'the assembly', Thing: 'The assembly' })
		i18n.global.locale.value = 'it'
		expect(kindNoun('assembly')).toEqual({ thing: "l'assemblea", Thing: "L'assemblea" })
		expect(kindNoun('session')).toEqual({ thing: 'la Sessione', Thing: 'La Sessione' })
	})
})
