// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/** The organizer UI's catalogue, one fragment per area so a translator (or a
 * reviewer) opens the Live tab's strings without scrolling past Settings'.
 * Keys read `organizer.<area>.<...>`; the parity test covers every fragment
 * through the merged catalogues exported by ../index.ts. */
import { catalogues, i18n, SUPPORTED_LOCALES, type SupportedLocale } from '../index'
import liveDe from './live.de.json'
import liveEn from './live.en.json'
import liveEs from './live.es.json'
import liveFr from './live.fr.json'
import liveIt from './live.it.json'
import navigationDe from './navigation.de.json'
import navigationEn from './navigation.en.json'
import navigationEs from './navigation.es.json'
import navigationFr from './navigation.fr.json'
import navigationIt from './navigation.it.json'
import resultsDe from './results.de.json'
import resultsEn from './results.en.json'
import resultsEs from './results.es.json'
import resultsFr from './results.fr.json'
import resultsIt from './results.it.json'
import settingsDe from './settings.de.json'
import settingsEn from './settings.en.json'
import settingsEs from './settings.es.json'
import settingsFr from './settings.fr.json'
import settingsIt from './settings.it.json'
import setupDe from './setup.de.json'
import setupEn from './setup.en.json'
import setupEs from './setup.es.json'
import setupFr from './setup.fr.json'
import setupIt from './setup.it.json'
import shellDe from './shell.de.json'
import shellEn from './shell.en.json'
import shellEs from './shell.es.json'
import shellFr from './shell.fr.json'
import shellIt from './shell.it.json'

export const organizerEn = {
	shell: shellEn,
	navigation: navigationEn,
	setup: setupEn,
	live: liveEn,
	results: resultsEn,
	settings: settingsEn,
}

export const organizerIt = {
	shell: shellIt,
	navigation: navigationIt,
	setup: setupIt,
	live: liveIt,
	results: resultsIt,
	settings: settingsIt,
}

export const organizerDe = {
	shell: shellDe,
	navigation: navigationDe,
	setup: setupDe,
	live: liveDe,
	results: resultsDe,
	settings: settingsDe,
}

export const organizerFr = {
	shell: shellFr,
	navigation: navigationFr,
	setup: setupFr,
	live: liveFr,
	results: resultsFr,
	settings: settingsFr,
}

export const organizerEs = {
	shell: shellEs,
	navigation: navigationEs,
	setup: setupEs,
	live: liveEs,
	results: resultsEs,
	settings: settingsEs,
}

/** One fragment set per shipped language; the loops below and the parity
 * test both read this, so a sixth language is one entry here. */
export const organizerFragments: Record<SupportedLocale, typeof organizerEn> = {
	en: organizerEn,
	it: organizerIt,
	de: organizerDe,
	fr: organizerFr,
	es: organizerEs,
}

/** The whole catalogue per language, shared file plus organizer fragments —
 * what the organizer app runs on, and what the parity test checks. */
export const organizerCatalogues = Object.fromEntries(
	SUPPORTED_LOCALES.map((locale) => [
		locale,
		{ ...catalogues[locale], organizer: organizerFragments[locale] },
	]),
) as Record<SupportedLocale, typeof catalogues.en & { organizer: typeof organizerEn }>

let installed = false
/** Merge the organizer's strings into the running i18n instance. Called by
 * the organizer entry (and the test mount helper); idempotent. */
export function installOrganizerCatalogue(): void {
	if (installed) return
	installed = true
	for (const locale of SUPPORTED_LOCALES) {
		i18n.global.mergeLocaleMessage(locale, { organizer: organizerFragments[locale] })
	}
}
