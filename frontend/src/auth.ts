// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Who is signed in, for the standalone mode.
 *
 * Plain reactive state with no imports from api.ts: the shell and the
 * Settings cards read it, and a spec sets it directly. In Nextcloud mode
 * `config` says so (or stays null) and nothing here is ever used.
 */
import { computed, reactive } from 'vue'
import type { Account, AuthConfig } from './types'

export const auth = reactive<{ config: AuthConfig | null; account: Account | null }>({
	config: null,
	account: null,
})

export const isStandalone = computed(() => auth.config?.mode === 'standalone')
