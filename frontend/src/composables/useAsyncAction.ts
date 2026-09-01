// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Running an action the user asked for, once.
 *
 * The `busy` guard is not cosmetic. Several handlers had none, so a
 * double-click reordered a round twice, added the same participant twice, or
 * imported a fifty-person CSV twice — all of which a facilitator does under
 * time pressure with a trackpad.
 */
import { ref } from 'vue'
import { describeError, type UiError } from '../errors'

export function useAsyncAction() {
	const busy = ref(false)
	const error = ref<UiError | null>(null)

	/** Returns true if the action ran and succeeded. */
	async function run(action: () => Promise<unknown>): Promise<boolean> {
		if (busy.value) return false // the second click of a double-click
		busy.value = true
		error.value = null
		try {
			await action()
			return true
		} catch (err) {
			error.value = describeError(err)
			return false
		} finally {
			busy.value = false
		}
	}

	return { busy, error, run }
}
