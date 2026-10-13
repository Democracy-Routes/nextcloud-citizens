/*
 * Driving one table's phone in a browser test.
 *
 * A "phone" is a browser CONTEXT, never a second page: localStorage and
 * IndexedDB are per-context, and two pages in one context would share the
 * recorder session key and the same audio store — the two phones would fight
 * over each other's state instead of behaving like two devices.
 *
 * Fake-media preferences are set at launch level in playwright.config.ts, so a
 * context created here inherits a working fake microphone.
 */
import { execSync } from 'node:child_process'
import { expect, type Browser, type BrowserContext, type Page } from '@playwright/test'

/** 2-second chunks so a "round" is seconds rather than minutes. */
export const CHUNK_MS = 2000

/** Capture stderr rather than letting it through: creating the app inside the
 * container configures structlog, and its startup chatter would otherwise bury
 * the test report. It is still attached to the error if the command fails. */
const SHELL = {
	encoding: 'utf-8' as const,
	stdio: ['ignore', 'pipe', 'pipe'] as ('ignore' | 'pipe')[],
}

export interface Seed {
	assembly_id: string
	round_id: string
	token: string
}

export function seed(): Seed {
	const output = execSync('sh ../scripts/browser-test-env.sh seed', SHELL)
	return JSON.parse(output.trim()) as Seed
}

/** Make an organizer API call.
 *
 * Not over HTTP: disabling the AppAPI middleware does not open the organizer
 * routes, because nc_py_api then checks the request signature inline instead,
 * and every organizer call would need a real Nextcloud signature. So the
 * container makes the call for us, through the real router with the identity
 * stubbed — see citizens/devtools.py. The endpoints themselves are covered by
 * tests/integration/; what a browser test needs is the effect.
 */
export function organizerApi<T = unknown>(
	method: string,
	path: string,
	body?: unknown,
): { status: number; body: T } {
	const args = body ? ` '${JSON.stringify(body).replace(/'/g, "'\\''")}'` : ''
	const output = execSync(
		`sh ../scripts/browser-test-env.sh api ${method} '${path}'${args}`,
		SHELL,
	)
	const line = output.split('\n').find((l) => l.startsWith('CITIZENS_API_RESULT:'))
	if (!line) throw new Error(`no result from the api bridge:\n${output}`)
	return JSON.parse(line.slice('CITIZENS_API_RESULT:'.length)) as { status: number; body: T }
}

export interface Phone {
	context: BrowserContext
	page: Page
	/** Scan the table's QR code and get as far as the microphone test. */
	join(): Promise<void>
	/** Join and record. Orchestrated mode auto-starts once armed. */
	record(): Promise<void>
	/** How many audio chunks are sitting in this phone's own storage. */
	localChunks(): Promise<number>
	/** This phone's recording id, as it knows it. */
	recordingId(): Promise<string | null>
	/** Close the browser abruptly — indistinguishable, to the server, from a
	 * battery dying: chunks simply stop arriving. */
	die(): Promise<void>
}

/** Get past the notice the way a person does: read to the end, then accept.
 *
 * Accept is scroll-gated to the end of the notice (0.8): the frame itself
 * scrolls, never the page, so jump it to the bottom first. Tolerant of no
 * notice at all (a device that already consented, a server before 0.7). */
export async function acceptNotice(page: Page): Promise<void> {
	const agree = page.getByRole('button', { name: /continue/ })
	await agree.waitFor({ state: 'visible', timeout: 20_000 }).catch(() => undefined)
	if (!(await agree.isVisible())) return
	const frame = page.locator('.rc-notice-frame')
	if (await frame.count()) {
		await frame.evaluate((el) => {
			el.scrollTop = el.scrollHeight
		})
	}
	await expect(agree).toBeEnabled({ timeout: 20_000 })
	await agree.click()
}

export async function newPhone(browser: Browser, token: string): Promise<Phone> {
	const context = await browser.newContext()
	const page = await context.newPage()

	async function join(): Promise<void> {
		await page.goto(`/recorder.html?chunkms=${CHUNK_MS}#/join/${encodeURIComponent(token)}`)
		// The notice screen is shown once per device and every phone here is a
		// fresh context, so it will appear — but waitFor, not isVisible:
		// isVisible() answers immediately and ignores a timeout, which races
		// the app's first render and silently skips the click. Assemblies made
		// here are 'optional' (the API default), so "Everyone added — continue"
		// is enabled without registering anyone.
		await acceptNotice(page)
		await expect(page.getByText('Microphone test')).toBeVisible({ timeout: 20_000 })
	}

	return {
		context,
		page,
		join,
		async record(): Promise<void> {
			await join()
			await expect(page.getByRole('button', { name: 'READY' })).toBeEnabled({ timeout: 20_000 })
			await page.getByRole('button', { name: 'READY' }).click()
			await expect(page.getByText('RECORDING', { exact: true })).toBeVisible({ timeout: 25_000 })
		},
		async localChunks(): Promise<number> {
			return page.evaluate(
				() =>
					new Promise<number>((resolve, reject) => {
						const open = indexedDB.open('citizens-recorder')
						open.onsuccess = () => {
							const store = open.result
								.transaction('chunks', 'readonly')
								.objectStore('chunks')
								.count()
							store.onsuccess = () => resolve(store.result)
							store.onerror = () => reject(store.error)
						}
						open.onerror = () => reject(open.error)
					}),
			)
		},
		async recordingId(): Promise<string | null> {
			return page.evaluate(
				() =>
					new Promise<string | null>((resolve) => {
						const open = indexedDB.open('citizens-recorder')
						open.onsuccess = () => {
							const all = open.result
								.transaction('recordings', 'readonly')
								.objectStore('recordings')
								.getAll()
							all.onsuccess = () => {
								const real = (all.result as { recordingId: string }[]).filter(
									(r) => r.recordingId !== '__selftest__',
								)
								resolve(real.length ? real[real.length - 1].recordingId : null)
							}
							all.onerror = () => resolve(null)
						}
						open.onerror = () => resolve(null)
					}),
			)
		},
		async die(): Promise<void> {
			await context.close()
		},
	}
}

// ---------------------------------------------------------------- organizer
// CITIZENS_INSECURE_NO_AUTH=1 on the throwaway instance, so these need no
// credentials — the same calls the facilitator's screen makes.

export interface MonitorTable {
	number: number
	table_id: string
	device: { connected: boolean; seconds_since_contact: number | null }
	recording: { id: string; state: string; received_chunks: number } | null
	superseded_recordings: { id: string; state: string }[]
	// one entry per recorder slot (services/rounds.py:_table_recorders) — this
	// is where a side-by-side second recorder's own state lives; `recording`
	// above only ever reflects the table's newest recording
	recorders: {
		slot: number
		recording: {
			id: string
			state: string
			live_source: boolean
			silent_seconds: number | null
		} | null
	}[]
	// machine-readable "can this table record" (services/readiness.py)
	readiness: {
		status: string
		reasons: { code: string; severity: string; slot: number | null }[]
	}
}

export function monitor(roundId: string): { tables: MonitorTable[] } {
	const result = organizerApi<{ tables: MonitorTable[] }>(
		'GET',
		`/api/v1/rounds/${roundId}/monitor`,
	)
	expect(result.status, JSON.stringify(result.body)).toBe(200)
	return result.body
}

export function tableOne(roundId: string): MonitorTable {
	const { tables } = monitor(roundId)
	const table = tables.find((t) => t.number === 1)
	expect(table, 'table 1 missing from the monitor').toBeTruthy()
	return table as MonitorTable
}

/** Poll the monitor until table 1's recording reaches one of these states.
 *
 * `table.recording` is only ever the table's NEWEST recording, and
 * `superseded_recordings` only the ones a replacement took over from — so
 * neither sees an older sibling that is still recording side by side and
 * never gets superseded (stall.spec.ts's two-recorders case). `recorders[]`
 * covers that: one entry per slot, each with its own recording's state. */
export async function waitForState(
	roundId: string,
	recordingId: string,
	states: string[],
	timeoutMs = 90_000,
): Promise<string> {
	const deadline = Date.now() + timeoutMs
	let last = ''
	while (Date.now() < deadline) {
		const { tables } = monitor(roundId)
		for (const table of tables) {
			const candidates = [
				table.recording,
				...(table.superseded_recordings ?? []),
				...table.recorders.map((r) => r.recording),
			]
			for (const candidate of candidates) {
				if (candidate && candidate.id === recordingId) {
					last = candidate.state
					if (states.includes(last)) return last
				}
			}
		}
		await new Promise((resolve) => setTimeout(resolve, 1000))
	}
	throw new Error(`recording ${recordingId} stayed in ${last || 'unknown'}, wanted ${states}`)
}
