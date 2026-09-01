// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Translation for both bundles.
 *
 * The deployment is Italian. Every string used to be an English literal in a
 * template, including the consent text a citizen taps to agree to being
 * recorded — so a room discussing Italian mobility policy, producing an
 * Italian transcript and an Italian report, read English instructions.
 *
 * Catalogues are plain JSON so a translator can work on them without touching
 * code, and tests/frontend/i18n-catalogue.spec.ts fails the build if a key
 * exists in English but not in Italian. Untranslated text cannot reach a
 * phone by being forgotten.
 */
import { createI18n } from 'vue-i18n'
import en from './en.json'
import it from './it.json'

export const SUPPORTED_LOCALES = ['en', 'it'] as const
export type SupportedLocale = (typeof SUPPORTED_LOCALES)[number]

export const DEFAULT_LOCALE: SupportedLocale = 'en'

export const i18n = createI18n({
	legacy: false,
	locale: DEFAULT_LOCALE,
	fallbackLocale: DEFAULT_LOCALE,
	messages: { en, it },
})

/** Narrow anything — a BCP-47 tag, an assembly's language — to a locale we
 * actually have a catalogue for. */
export function resolveLocale(candidate: string | null | undefined): SupportedLocale {
	const base = (candidate ?? '').toLowerCase().split('-')[0]
	return (SUPPORTED_LOCALES as readonly string[]).includes(base)
		? (base as SupportedLocale)
		: DEFAULT_LOCALE
}

export function setLocale(candidate: string | null | undefined): SupportedLocale {
	const locale = resolveLocale(candidate)
	i18n.global.locale.value = locale
	// screen readers and hyphenation both depend on this being right
	document.documentElement.lang = locale
	return locale
}

/** Translate outside a component (composables, plain modules). */
export function t(key: string, named?: Record<string, unknown>): string {
	return named
		? (i18n.global.t(key, named) as string)
		: (i18n.global.t(key) as string)
}
