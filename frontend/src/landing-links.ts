// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Where the standalone sign-in page points: the project site that describes
 * Democracy Routes, and the brand line. Kept out of the templates so the
 * no-untranslated-strings spec sees constants, not literals. */
export const LANDING_LINKS = {
	DEMOCRACY_ROUTES_URL: 'https://democracyroutes.com',
	POWERED_BY: 'Powered by democracyroutes.com',
} as const
