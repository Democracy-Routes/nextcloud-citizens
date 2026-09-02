/*
 * A phone that is offline rather than dead.
 *
 * This is the test the whole design turns on. The server cannot tell a flat
 * battery from dead WiFi — both simply go silent — so the two ways of releasing
 * a table behave differently on purpose:
 *
 *   * the organizer pressing "replace device" looked at the phone, so the
 *     recording is finished on the spot;
 *   * the automatic takeover is a timer guessing, so it leaves the recording
 *     open, because a merely disconnected phone is still recording and will
 *     bring its backlog when the network returns.
 *
 * Nothing else proves that second half. It needs a real MediaRecorder writing
 * to real IndexedDB while the network is down, which only a browser can do.
 */
import { expect, test } from '@playwright/test'
import { CHUNK_MS, newPhone, seed, tableOne } from './support/phone'

// STALLED_DEVICE_SECONDS is 120 and the config allows 180 per test, which
// leaves no room for setup. Only this test waits it out.
const TAKEOVER_WAIT_MS = 135_000

test('a disconnected phone keeps its audio and a replacement still gets the table', async ({ browser }) => {
	test.setTimeout(300_000)
	const fixture = seed()

	const phoneA = await newPhone(browser, fixture.token)
	await phoneA.record()
	await phoneA.page.waitForTimeout(CHUNK_MS * 3)

	const firstRecording = await phoneA.recordingId()
	const uploadedBefore = tableOne(fixture.round_id).recording?.received_chunks ?? 0
	expect(uploadedBefore).toBeGreaterThan(0)

	// --- the WiFi drops. The phone is fine and keeps recording. ---
	await phoneA.context.setOffline(true)
	await expect(phoneA.page.getByText('Network unavailable', { exact: false })).toBeVisible({
		timeout: 25_000,
	})

	const bufferedStart = await phoneA.localChunks()
	await phoneA.page.waitForTimeout(TAKEOVER_WAIT_MS)
	expect(
		await phoneA.localChunks(),
		'the phone stopped recording when it lost the network',
	).toBeGreaterThan(bufferedStart)

	// --- the table gives up waiting and uses another phone. Nobody presses
	//     anything: this is the automatic path. ---
	const phoneB = await newPhone(browser, fixture.token)
	await phoneB.record()

	const duringTakeover = tableOne(fixture.round_id)
	expect(duringTakeover.recording?.id).not.toBe(firstRecording)
	expect(duringTakeover.superseded_recordings.map((r) => r.id)).toContain(firstRecording)

	// --- and the point of it all: phone A comes back and its buffered audio
	//     still lands, because nothing finished its recording behind its back ---
	await phoneA.context.setOffline(false)

	await expect
		.poll(
			() => {
				const table = tableOne(fixture.round_id)
				const superseded = table.superseded_recordings.find((r) => r.id === firstRecording)
				return superseded?.state ?? ''
			},
			{ timeout: 90_000 },
		)
		.toBe('WAITING_FOR_CHUNKS')

	await phoneA.context.close()
	await phoneB.context.close()
})
