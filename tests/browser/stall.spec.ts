/*
 * R22: a recorder goes silent WITHOUT dying, while a sibling at the same
 * table keeps sending — "stall injection".
 *
 * A dead phone (device-replacement.spec.ts) and a merely offline one with no
 * backup (device-offline.spec.ts) are both covered elsewhere. This is the
 * third way a recorder can go quiet, and the only one that needs TWO
 * recorders at once: the readiness CAPTURE_SILENT warning (30 s without a
 * chunk, services/readiness.py) and the live-caption failover
 * (live_source.take_over_if_stalled, services/live_source.py) read the exact
 * same silence clock, so one stalled phone with a healthy sibling must show
 * up as a warning on the Live tab AND hand the captions to the sibling —
 * never finish the recording on its own, because the phone is still
 * recording and may yet come back (same reasoning as device-offline.spec.ts).
 * And when the phone returns, both the warning and the backlog upload must
 * resolve themselves, with nothing for the organizer to press.
 */
import { expect, test, type Page } from '@playwright/test'
import { CHUNK_MS, newPhone, organizerApi, seed, tableOne, waitForState, acceptNotice } from './support/phone'

async function finish(page: Page): Promise<void> {
	await page.getByRole('button', { name: 'Finish recording', exact: true }).click()
	await page.getByRole('button', { name: 'Yes, finish and synchronize' }).click()
}

/** This phone's own bearer, straight from its session storage — the same
 * value every recorder call it makes already carries (RecorderApp.vue's
 * SESSION_KEY). Needed to make the capability AS phone A, not as the test. */
async function bearerOf(page: Page): Promise<string> {
	const raw = await page.evaluate(() => localStorage.getItem('citizens-recorder-session'))
	const session = JSON.parse(raw ?? '{}') as { session_token?: string }
	if (!session.session_token) throw new Error('phone has no recorder session yet')
	return session.session_token
}

/** A phone scanning an ADD_RECORDER_TO_TABLE code sees one screen the table's
 * own code never shows — "You join as Recorder B", its own "Continue" — before
 * falling into the ordinary notice/mic-test flow that support/phone.ts's
 * join() already knows. Written out here rather than folded into that shared
 * helper, since no other spec joins through a capability. */
async function joinAsAddedRecorder(page: Page, token: string): Promise<void> {
	await page.goto(`/recorder.html?chunkms=${CHUNK_MS}#/join/${encodeURIComponent(token)}`)
	// since 0.8 "You join as Recorder B" is one line on the notice itself,
	// not a screen of its own: one gated Accept, as for any phone
	await acceptNotice(page)
	await expect(page.getByText('Microphone test')).toBeVisible({ timeout: 20_000 })
	await expect(page.getByRole('button', { name: 'READY' })).toBeEnabled({ timeout: 20_000 })
	await page.getByRole('button', { name: 'READY' }).click()
	await expect(page.getByText('RECORDING', { exact: true })).toBeVisible({ timeout: 25_000 })
}

/** received_chunks per recording, slot or no slot: the monitor's per-slot
 * `recorders[]` entries never carry it (services/rounds.py:_table_recorders),
 * only the table's single newest `recording` does — and once a second phone
 * exists that newest one is B's, not A's. The organizer's own "every
 * recording of this table" list is the one place both still show up. */
function receivedChunks(roundId: string, tableId: string, recordingId: string): number {
	const result = organizerApi<{ id: string; received_chunks: number }[]>(
		'GET',
		`/api/v1/rounds/${roundId}/tables/${tableId}/recordings`,
	)
	expect(result.status, JSON.stringify(result.body)).toBe(200)
	const row = result.body.find((r) => r.id === recordingId)
	expect(row, `recording ${recordingId} missing from the table's recordings`).toBeTruthy()
	return row!.received_chunks
}

test('a stalled recorder keeps its warning and hands the captions to its sibling, then clears both when it returns', async ({ browser }) => {
	test.setTimeout(300_000)
	const fixture = seed()

	// --- phone A scans the table's own code: slot 1, and the table's first
	//     (so far only) recorder takes the live captions by default ---
	const phoneA = await newPhone(browser, fixture.token)
	await phoneA.record()
	await phoneA.page.waitForTimeout(CHUNK_MS * 3)

	const tableId = tableOne(fixture.round_id).table_id
	const recordingA = await phoneA.recordingId()
	expect(recordingA, 'phone A never registered a recording').toBeTruthy()
	expect(receivedChunks(fixture.round_id, tableId, recordingA as string)).toBeGreaterThan(0)

	// --- phone A makes an ADD_RECORDER_TO_TABLE code with its OWN bearer —
	//     the exact call the "Add recorder" button makes — and phone B scans
	//     it into slot 2, recording the same table side by side ---
	const capability = await phoneA.page.request.post('/api/v1/public/recorder/capabilities', {
		headers: { Authorization: `Bearer ${await bearerOf(phoneA.page)}` },
		data: { purpose: 'ADD_RECORDER_TO_TABLE' },
	})
	expect(capability.ok(), await capability.text()).toBeTruthy()
	const card = (await capability.json()) as { url: string }
	const tokenB = card.url.split('#/join/')[1]

	const phoneB = await newPhone(browser, tokenB)
	await joinAsAddedRecorder(phoneB.page, tokenB)
	await phoneB.page.waitForTimeout(CHUNK_MS * 3)

	const recordingB = await phoneB.recordingId()
	expect(recordingB, 'phone B never registered a recording').toBeTruthy()
	expect(recordingB).not.toBe(recordingA)

	// A started first, so A holds the captions and B is a backup, before
	// either one has gone anywhere near silent
	await expect
		.poll(() => {
			const recorders = tableOne(fixture.round_id).recorders
			return [
				recorders.find((r) => r.slot === 1)?.recording?.live_source,
				recorders.find((r) => r.slot === 2)?.recording?.live_source,
			]
		}, { timeout: 20_000 })
		.toEqual([true, false])

	const uploadedBeforeStall = receivedChunks(fixture.round_id, tableId, recordingA as string)

	// --- the WiFi drops. The phone keeps recording locally; only its uploads
	//     stop reaching the server — exactly device-offline.spec.ts's premise,
	//     now with a sibling present to take the captions over ---
	await phoneA.context.setOffline(true)
	await expect(phoneA.page.getByText('Network unavailable', { exact: false })).toBeVisible({
		timeout: 25_000,
	})

	// --- (1) the Live tab's readiness warns about A specifically, once the
	//     server has gone CAPTURE_SILENT_SECONDS (30 s) without a chunk. One
	//     monitor call per poll tick (not two) keeps the organizer bridge's own
	//     overhead from eating into the generous-but-bounded test budget ---
	let silentSeconds = 0
	await expect
		.poll(() => {
			const table = tableOne(fixture.round_id)
			silentSeconds = table.recorders.find((r) => r.slot === 1)?.recording?.silent_seconds ?? 0
			return table.readiness.reasons.some((r) => r.code === 'CAPTURE_SILENT' && r.slot === 1)
		}, { timeout: 60_000 })
		.toBe(true)
	expect(silentSeconds).toBeGreaterThanOrEqual(30)

	// --- (2) B's next chunk after that 30 s mark takes the live source over.
	//     This is a side effect of an upload landing, not a sweep, so it lands
	//     on B's own ~2 s cadence rather than the instant the clock hits 30 — a
	//     generous poll covers that plus any CI slowness ---
	await expect
		.poll(() => {
			const recorders = tableOne(fixture.round_id).recorders
			return [
				recorders.find((r) => r.slot === 1)?.recording?.live_source,
				recorders.find((r) => r.slot === 2)?.recording?.live_source,
			]
		}, { timeout: 60_000 })
		.toEqual([false, true])

	// --- (3) the WiFi returns: nobody touched the recording, so the backlog
	//     simply uploads and the warning clears by itself ---
	await phoneA.context.setOffline(false)
	await expect
		.poll(() => receivedChunks(fixture.round_id, tableId, recordingA as string), { timeout: 60_000 })
		.toBeGreaterThan(uploadedBeforeStall)
	await expect
		.poll(() => {
			const reasons = tableOne(fixture.round_id).readiness.reasons
			return reasons.some((r) => r.code === 'CAPTURE_SILENT' && r.slot === 1)
		}, { timeout: 60_000 })
		.toBe(false)

	// --- (4) both phones finish normally, and both halves of the table's
	//     discussion reach the server as real recordings — nothing about the
	//     stall left either of them stuck ---
	await Promise.all([finish(phoneA.page), finish(phoneB.page)])
	await Promise.all([
		expect(phoneA.page.getByText('Recording synchronized')).toBeVisible({ timeout: 90_000 }),
		expect(phoneB.page.getByText('Recording synchronized')).toBeVisible({ timeout: 90_000 }),
	])
	const completed = ['AUDIO_READY', 'TRANSCRIBING', 'TRANSCRIBED', 'TRANSCRIPTION_FAILED']
	const [stateA, stateB] = await Promise.all([
		waitForState(fixture.round_id, recordingA as string, completed),
		waitForState(fixture.round_id, recordingB as string, completed),
	])
	expect(stateA, "phone A's audio was never assembled").not.toBe('UPLOAD_INCOMPLETE')
	expect(stateB, "phone B's audio was never assembled").not.toBe('UPLOAD_INCOMPLETE')

	await phoneA.context.close()
	await phoneB.context.close()
})
