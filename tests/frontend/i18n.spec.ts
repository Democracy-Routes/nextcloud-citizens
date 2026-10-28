// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Translation must be complete, or it is worse than none.
 *
 * A half-translated interface is how a citizen in Bologna ends up reading
 * Italian instructions and then an English sentence about what happens to the
 * recording of their voice. The catalogue parity test below is what makes
 * "someone forgot the Italian" — or, since 0.9, the German, French or
 * Spanish — a build failure rather than something noticed on a phone during
 * an assembly.
 */
import { describe, expect, it } from 'vitest'
import { DEFAULT_LOCALE, i18n, resolveLocale, SUPPORTED_LOCALES } from '../../frontend/src/i18n'
import { installOrganizerCatalogue, organizerCatalogues as catalogues } from '../../frontend/src/i18n/organizer'

installOrganizerCatalogue()

// the merged catalogues: the shared file plus every organizer fragment, so a
// key added to one area's English and not another language fails here too
const en = catalogues.en
// named `italian`, not `it`: that would shadow vitest's own it()
const italian = catalogues.it
const OTHERS = SUPPORTED_LOCALES.filter((locale) => locale !== 'en')

function flatten(value: unknown, prefix = ''): string[] {
	if (typeof value !== 'object' || value === null) return [prefix]
	return Object.entries(value as Record<string, unknown>).flatMap(([key, child]) =>
		flatten(child, prefix ? `${prefix}.${key}` : key),
	)
}

function read(catalogue: unknown, key: string): unknown {
	return key.split('.').reduce<unknown>((node, part) => (node as Record<string, unknown>)?.[part], catalogue)
}

describe('the catalogues', () => {
	it('ship the five languages an assembly can be held in', () => {
		expect([...SUPPORTED_LOCALES].sort()).toEqual(['de', 'en', 'es', 'fr', 'it'])
	})

	it.each(OTHERS)('%s defines exactly the same keys as English', (locale) => {
		const english = flatten(en).sort()
		const translated = flatten(catalogues[locale]).sort()

		const missing = english.filter((key) => !translated.includes(key))
		const extra = translated.filter((key) => !english.includes(key))

		expect(missing, `not translated into ${locale}: ${missing.join(', ')}`).toEqual([])
		expect(extra, `in ${locale} but not English: ${extra.join(', ')}`).toEqual([])
	})

	it.each([...SUPPORTED_LOCALES])('%s leaves no string empty', (locale) => {
		const catalogue = catalogues[locale]
		const empties = flatten(catalogue).filter((key) => {
			const value = read(catalogue, key)
			return typeof value === 'string' && value.trim() === ''
		})
		expect(empties, `${locale} has empty strings: ${empties.join(', ')}`).toEqual([])
	})

	it.each(OTHERS)('%s keeps the same interpolation placeholders as English', (locale) => {
		// the SET of names: a language may spell a plural out in three branches
		// ("{count} tavoli | {count} tavolo | {count} tavoli") where the other
		// keeps one string — what must agree is which values are interpolated
		const placeholders = (text: string) =>
			[...new Set(text.match(/\{[a-zA-Z0-9_]+\}/g) ?? [])].sort().join(',')

		const differing: string[] = []
		for (const key of flatten(en)) {
			const source = read(en, key)
			const target = read(catalogues[locale], key)
			if (typeof source !== 'string' || typeof target !== 'string') continue
			if (placeholders(target) !== placeholders(source)) differing.push(key)
		}
		expect(differing, `placeholders differ in ${locale}: ${differing.join(', ')}`).toEqual([])
	})

	it.each(OTHERS)('%s is not a copy of the English', (locale) => {
		// a translator who pastes the English through is caught here: most
		// strings must differ (short labels like "OK" or "PDF" legitimately agree)
		const keys = flatten(en).filter((key) => typeof read(en, key) === 'string')
		const same = keys.filter((key) => read(en, key) === read(catalogues[locale], key))
		expect(same.length, `${locale} repeats the English in ${same.length} of ${keys.length} strings`).toBeLessThan(
			keys.length / 5,
		)
	})
})

describe('locale resolution', () => {
	it('accepts the languages we actually ship', () => {
		for (const locale of SUPPORTED_LOCALES) {
			expect(resolveLocale(locale)).toBe(locale)
		}
	})

	it('narrows a regional tag to its base language', () => {
		expect(resolveLocale('it-IT')).toBe('it')
		expect(resolveLocale('en-GB')).toBe('en')
		expect(resolveLocale('de-AT')).toBe('de')
		expect(resolveLocale('fr-CA')).toBe('fr')
		expect(resolveLocale('es-MX')).toBe('es')
	})

	it('falls back for a language we do not have', () => {
		expect(resolveLocale('pt')).toBe(DEFAULT_LOCALE)
		expect(resolveLocale('')).toBe(DEFAULT_LOCALE)
		expect(resolveLocale(null)).toBe(DEFAULT_LOCALE)
		expect(resolveLocale(undefined)).toBe(DEFAULT_LOCALE)
	})
})

describe('translation', () => {
	it('renders Italian when the assembly is Italian', () => {
		i18n.global.locale.value = 'it'
		const consent = i18n.global.t('recorder.consent.agree')
		expect(consent).toBe(italian.recorder.consent.agree)
		expect(consent).not.toBe(en.recorder.consent.agree)
		i18n.global.locale.value = 'en'
	})

	it.each(OTHERS)('renders the %s consent sentence, not the English one', (locale) => {
		i18n.global.locale.value = locale
		expect(i18n.global.t('recorder.consent.agree')).toBe(catalogues[locale].recorder.consent.agree)
		expect(i18n.global.t('recorder.consent.agree')).not.toBe(en.recorder.consent.agree)
		i18n.global.locale.value = 'en'
	})

	it('interpolates values rather than printing the placeholder', () => {
		i18n.global.locale.value = 'it'
		expect(i18n.global.t('recorder.consent.title', { number: 3 })).toContain('3')
		expect(i18n.global.t('recorder.consent.title', { number: 3 })).not.toContain('{number}')
		i18n.global.locale.value = 'en'
	})

	it.each(OTHERS)('%s uses the singular form for a one-day retention', (locale) => {
		i18n.global.locale.value = locale
		const oneDay = i18n.global.t('recorder.consent.retentionDays', { days: 1 }, 1)
		const manyDays = i18n.global.t('recorder.consent.retentionDays', { days: 30 }, 30)
		expect(oneDay).not.toBe(manyDays)
		expect(manyDays).toContain('30')
		i18n.global.locale.value = 'en'
	})
})
