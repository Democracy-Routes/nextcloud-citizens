// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/** The built-in Vosk engine's model manager, as the Settings page sees it:
 * the catalogue, install progress, and the install / cancel / remove
 * actions. Behaviour unchanged from the 0.8 Audio tab. */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../../api'
import { describeError } from '../../errors'
import type { VoskModelsResponse } from '../../types'
import { ASSEMBLY_LANGUAGES } from './useSettingsForm'

export interface VoskRow {
	name: string
	kind: 'small' | 'large' | 'custom'
	sizeMb: number
	installed: boolean
	inUse: boolean
	progress: { phase: string; received: number; total: number; error: string | null } | null
}

export const VOSK_POLL_MS = 3000

export function installing(progress: { phase: string } | null | undefined): boolean {
	return !!progress && ['queued', 'downloading', 'unpacking'].includes(progress.phase)
}

export function percent(progress: { received: number; total: number }): number {
	return progress.total > 0 ? Math.min(100, Math.round((progress.received / progress.total) * 100)) : 0
}

export function failureOf(row: VoskRow): string {
	return row.progress?.phase === 'failed' ? (row.progress.error ?? '') : ''
}

export function useVoskModels() {
	const catalog = ref<VoskModelsResponse | null>(null)
	const catalogError = ref('')
	const pendingRemove = ref('')
	const busy = ref('')
	let poll: ReturnType<typeof setTimeout> | null = null

	async function load(): Promise<void> {
		try {
			catalog.value = await api.voskModels()
			catalogError.value = ''
		} catch (err) {
			catalogError.value = describeError(err).message
		}
	}

	// Poll only while something is in flight: an idle Settings page must not
	// keep asking the server, and a download's bar must not freeze between
	// visits.
	watch(catalog, (value) => {
		if (poll) {
			clearTimeout(poll)
			poll = null
		}
		if (value?.available.some((m) => installing(m.progress))) {
			poll = setTimeout(() => void load(), VOSK_POLL_MS)
		}
	})
	onBeforeUnmount(() => {
		if (poll) clearTimeout(poll)
	})
	onMounted(() => void load())

	const groups = computed<Array<{ code: string; label: string; rows: VoskRow[] }>>(() => {
		const value = catalog.value
		if (!value) return []
		const inUse = value.engine?.in_use ?? {}
		const byLang = new Map<string, Map<string, VoskRow>>()
		const rowsFor = (code: string) => {
			if (!byLang.has(code)) byLang.set(code, new Map())
			return byLang.get(code)!
		}
		for (const m of value.available) {
			rowsFor(m.language).set(m.name, {
				name: m.name,
				kind: m.kind,
				sizeMb: m.size_mb,
				installed: false,
				inUse: false,
				progress: m.progress,
			})
		}
		for (const m of value.installed) {
			const rows = rowsFor(m.language)
			const row = rows.get(m.name)
			if (row) {
				row.installed = true
			} else {
				rows.set(m.name, {
					name: m.name,
					kind: m.kind,
					sizeMb: Math.max(1, Math.round(m.size_bytes / 1048576)),
					installed: true,
					inUse: false,
					progress: null,
				})
			}
			rows.get(m.name)!.inUse = (inUse[m.name] ?? 0) > 0
		}
		const known = ASSEMBLY_LANGUAGES.map((l) => l.code)
		const others = [...byLang.keys()].filter((c) => !known.includes(c)).sort()
		return [...known, ...others]
			.filter((code) => byLang.has(code))
			.map((code) => ({
				code,
				label: ASSEMBLY_LANGUAGES.find((l) => l.code === code)?.label ?? code,
				rows: [...byLang.get(code)!.values()],
			}))
	})

	async function action(name: string, call: () => Promise<unknown>): Promise<void> {
		busy.value = name
		try {
			await call()
		} catch (err) {
			catalogError.value = describeError(err).message
		} finally {
			busy.value = ''
		}
		await load()
	}

	const install = (name: string) => action(name, () => api.voskModelInstall(name))
	const cancel = (name: string) => action(name, () => api.voskModelCancel(name))
	async function remove(name: string): Promise<void> {
		pendingRemove.value = ''
		await action(name, () => api.voskModelRemove(name))
	}

	/** The models a language's picker offers: what is installed and usable,
	 * plus the saved value even when it is gone — hiding it would make the
	 * select look empty and a save silently drop the setting. */
	function choices(code: string, current: string): Array<{ name: string; missing: boolean }> {
		const names = (catalog.value?.installed ?? [])
			.filter((m) => m.language === code && m.usable)
			.map((m) => ({ name: m.name, missing: false }))
		if (current && !names.some((m) => m.name === current)) names.push({ name: current, missing: true })
		return names
	}

	const memoryMb = computed(() => {
		const bytes = catalog.value?.memory_available_bytes
		return bytes == null ? null : Math.floor(bytes / 1048576)
	})

	return { catalog, catalogError, pendingRemove, busy, groups, memoryMb, load, install, cancel, remove, choices }
}
