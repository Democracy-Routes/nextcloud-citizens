// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/** The API base URL is derived from the organizer's own <script> tag. Since
 * 0.8 that tag is the versioned bundle injected by the loader, not the
 * registered `js/citizens-main.js`: both spellings must resolve to the app
 * root, or every API call fetches the bundle (seen live on 2026-10-26). */
import { describe, expect, it } from 'vitest'
import { baseFromScriptSrc } from '../../frontend/src/api'

const PROXY = 'https://cloud.example.org/apps/app_api/proxy/citizens'

describe('API base URL detection', () => {
	it('strips the registered loader name', () => {
		expect(baseFromScriptSrc(`${PROXY}/js/citizens-main.js`)).toBe(PROXY)
	})

	it('strips the versioned bundle the loader injects', () => {
		expect(baseFromScriptSrc(`${PROXY}/js/citizens-main.bundle.js?v=0.8.0-alpha.1`)).toBe(PROXY)
	})

	it('works through an /exapps rewrite', () => {
		expect(
			baseFromScriptSrc('https://cloud.example.org/exapps/citizens/js/citizens-main.bundle.js?v=1'),
		).toBe('https://cloud.example.org/exapps/citizens')
	})
})
