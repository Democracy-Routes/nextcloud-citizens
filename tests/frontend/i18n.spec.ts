// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Translation must be complete, or it is worse than none.
 *
 * A half-translated interface is how a citizen in Bologna ends up reading
 * Italian instructions and then an English sentence about what happens to the
 * recording of their voice. The catalogue parity test below is what makes
 * "someone forgot the Italian" a build failure rather than something noticed
 * on a phone during an assembly.
 */
import { describe, expect, it } from 'vitest'
import en from '../../frontend/src/i18n/en.json'
// named `italian`, not `it`: that would shadow vitest's own it()
import italian from '../../frontend/src/i18n/it.json'
import { DEFAULT_LOCALE, i18n, resolveLocale, SUPPORTED_LOCALES } from '../../frontend/src/i18n'

function flatten(value: unknown, prefix = ''): string[] {
	if (typeof value !== 'object' || value === null) return [prefix]
	return Object.entries(value as Record<string, unknown>).flatMap(([key, child]) =>
		flatten(child, prefix ? `${prefix}.${key}` : key),
	)
}

describe('the catalogues', () => {
	it('define exactly the same keys in every language', () => {
		const english = flatten(en).sort()
		const italianKeys = flatten(italian).sort()

		const missing = english.filter((key) => !italianKeys.includes(key))
		const extra = italianKeys.filter((key) => !english.includes(key))

		expect(missing, `not translated into Italian: ${missing.join(', ')}`).toEqual([])
		expect(extra, `in Italian but not English: ${extra.join(', ')}`).toEqual([])
	})

	it('leaves no string empty', () => {
		for (const [name, catalogue] of [['en', en], ['it', italian]] as const) {
			const empties = flatten(catalogue).filter((key) => {
				const value = key
					.split('.')
					.reduce<unknown>((node, part) => (node as Record<string, unknown>)?.[part], catalogue)
				return typeof value === 'string' && value.trim() === ''
			})
			expect(empties, `${name} has empty strings: ${empties.join(', ')}`).toEqual([])
		}
	})

	it('keeps the same interpolation placeholders in both languages', () => {
		const placeholders = (text: string) =>
			(text.match(/\{[a-zA-Z0-9_]+\}/g) ?? []).sort().join(',')

		for (const key of flatten(en)) {
			const read = (catalogue: unknown) =>
				key.split('.').reduce<unknown>((node, part) => (node as Record<string, unknown>)?.[part], catalogue)
			const source = read(en)
			const target = read(italian)
			if (typeof source !== 'string' || typeof target !== 'string') continue
			expect(placeholders(target), `placeholders differ in ${key}`).toBe(placeholders(source))
		}
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
	})

	it('falls back for a language we do not have', () => {
		expect(resolveLocale('de')).toBe(DEFAULT_LOCALE)
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

	it('interpolates values rather than printing the placeholder', () => {
		i18n.global.locale.value = 'it'
		expect(i18n.global.t('recorder.consent.title', { number: 3 })).toContain('3')
		expect(i18n.global.t('recorder.consent.title', { number: 3 })).not.toContain('{number}')
		i18n.global.locale.value = 'en'
	})

	it('uses the singular form for a one-day retention', () => {
		i18n.global.locale.value = 'it'
		const oneDay = i18n.global.t('recorder.consent.retentionDays', { days: 1 }, 1)
		const manyDays = i18n.global.t('recorder.consent.retentionDays', { days: 30 }, 30)
		expect(oneDay).not.toBe(manyDays)
		expect(manyDays).toContain('30')
		i18n.global.locale.value = 'en'
	})
})
