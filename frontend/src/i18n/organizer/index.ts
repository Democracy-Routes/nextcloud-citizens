// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/** The organizer UI's catalogue, one fragment per area so a translator (or a
 * reviewer) opens the Live tab's strings without scrolling past Settings'.
 * Keys read `organizer.<area>.<...>`; the parity test covers every fragment
 * through the merged catalogues exported by ../index.ts. */
import { catalogues, i18n } from '../index'
import liveEn from './live.en.json'
import liveIt from './live.it.json'
import navigationEn from './navigation.en.json'
import navigationIt from './navigation.it.json'
import resultsEn from './results.en.json'
import resultsIt from './results.it.json'
import settingsEn from './settings.en.json'
import settingsIt from './settings.it.json'
import setupEn from './setup.en.json'
import setupIt from './setup.it.json'
import shellEn from './shell.en.json'
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

/** The whole catalogue per language, shared file plus organizer fragments —
 * what the organizer app runs on, and what the parity test checks. */
export const organizerCatalogues = {
	en: { ...catalogues.en, organizer: organizerEn },
	it: { ...catalogues.it, organizer: organizerIt },
}

let installed = false
/** Merge the organizer's strings into the running i18n instance. Called by
 * the organizer entry (and the test mount helper); idempotent. */
export function installOrganizerCatalogue(): void {
	if (installed) return
	installed = true
	i18n.global.mergeLocaleMessage('en', { organizer: organizerEn })
	i18n.global.mergeLocaleMessage('it', { organizer: organizerIt })
}
