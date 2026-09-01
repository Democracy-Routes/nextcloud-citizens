// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Loading something from the API, with the states a facilitator needs.
 *
 * Five components had no catch on their initial load at all, so an API outage
 * gave an unhandled rejection and a lying empty state — the worst being the
 * sidebar, which said "No assemblies yet" and invited the facilitator to
 * create the assembly they already had, during the event.
 *
 * `loadedAt` is here rather than in the polling layer because staleness is a
 * property of the data, and the freshness stamp has to keep working for the
 * tabs that only load once.
 */
import { ref, type Ref } from 'vue'
import { describeError, type UiError } from '../errors'

export interface AsyncData<T> {
	data: Ref<T | null>
	error: Ref<UiError | null>
	/** True only while there is nothing to show yet — a refresh of existing
	 * data must not blank the screen during a live event. */
	loading: Ref<boolean>
	refreshing: Ref<boolean>
	loadedAt: Ref<Date | null>
	reload: () => Promise<void>
}

export function useAsyncData<T>(
	load: () => Promise<T>,
	options: { immediate?: boolean } = {},
): AsyncData<T> {
	const data = ref<T | null>(null) as Ref<T | null>
	const error = ref<UiError | null>(null)
	const loading = ref(false)
	const refreshing = ref(false)
	const loadedAt = ref<Date | null>(null)
	let inFlight: Promise<void> | null = null

	async function reload(): Promise<void> {
		// collapse concurrent calls: a poll and a manual refresh landing
		// together used to race, and whichever finished last won
		if (inFlight) return inFlight
		if (data.value === null) loading.value = true
		else refreshing.value = true
		inFlight = (async () => {
			try {
				data.value = await load()
				error.value = null
				loadedAt.value = new Date()
			} catch (err) {
				error.value = describeError(err)
			} finally {
				loading.value = false
				refreshing.value = false
				inFlight = null
			}
		})()
		return inFlight
	}

	if (options.immediate !== false) void reload()

	return { data, error, loading, refreshing, loadedAt, reload }
}
