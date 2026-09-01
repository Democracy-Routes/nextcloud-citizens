// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Mount a component the way the app does.
 *
 * Both bundles install vue-i18n, so any component calling useI18n() needs the
 * plugin present or it throws "Need to install with `app.use` function".
 * Tests assert on English, the source language, so a copy change shows up as a
 * visible test change rather than silently passing.
 */
import { mount } from '@vue/test-utils'
import { i18n } from '../../../frontend/src/i18n'

type MountArgs = Parameters<typeof mount>

export function mountWithI18n(component: MountArgs[0], options: MountArgs[1] = {}) {
	i18n.global.locale.value = 'en'
	return mount(component, {
		...options,
		global: {
			...(options.global ?? {}),
			plugins: [...((options.global?.plugins as unknown[]) ?? []), i18n],
		},
	} as MountArgs[1])
}
