/*
 * A table's phone dies mid-round and another one takes over.
 *
 * Runs the real recorder — MediaRecorder, IndexedDB, the join flow, the upload
 * engine — none of which the Python or component suites touch. To the server a
 * dead battery IS a closed tab: chunks simply stop arriving. So closing a
 * browser context reproduces a dead phone exactly rather than approximately.
 *
 * Needs the throwaway instance: `make test-browser`, or
 * `sh scripts/browser-test-env.sh start` then `npx playwright test`.
 */
import { expect, test } from '@playwright/test'
import { CHUNK_MS, newPhone, organizerApi, seed, tableOne, waitForState } from './support/phone'

test('the organizer hands a dead table to another phone', async ({ browser }) => {
	const fixture = seed()

	// --- phone A records, and some of the round reaches the server ---
	const phoneA = await newPhone(browser, fixture.token)
	await phoneA.record()
	await phoneA.page.waitForTimeout(CHUNK_MS * 3)

	const firstRecording = await phoneA.recordingId()
	expect(firstRecording, 'phone A never registered a recording').toBeTruthy()
	await expect
		.poll(() => tableOne(fixture.round_id).recording?.received_chunks ?? 0, { timeout: 30_000 })
		.toBeGreaterThan(0)

	// --- the battery dies ---
	await phoneA.die()

	// --- a second phone scans the same printed code ---
	const phoneB = await newPhone(browser, fixture.token)
	await phoneB.page.goto(
		`/recorder.html?chunkms=${CHUNK_MS}#/join/${encodeURIComponent(fixture.token)}`,
	)
	const agree = phoneB.page.getByRole('button', { name: /Everyone at this table agrees/ })
	await agree.waitFor({ state: 'visible', timeout: 20_000 })
	await agree.click()
	await expect(phoneB.page.getByRole('button', { name: 'READY' })).toBeEnabled({ timeout: 20_000 })
	await phoneB.page.getByRole('button', { name: 'READY' }).click()

	// Told the truth about why it cannot start: the round is being recorded on
	// another phone. NOT "this table has completed every round", which is what
	// it used to say at the exact moment a table's device had just died.
	await expect(phoneB.page.getByText(/already recording on another phone/)).toBeVisible({
		timeout: 25_000,
	})
	await expect(phoneB.page.getByText('completed every round')).toHaveCount(0)

    // --- the facilitator releases the table ---
	const released = organizerApi<{ assembling: boolean }>(
		'POST',
		`/api/v1/recordings/${firstRecording}/replace-device`,
	)
	expect(released.status, JSON.stringify(released.body)).toBe(200)
	expect(released.body.assembling).toBe(true)

	// --- phone B carries on, with nobody touching it ---
	// It is already armed and polling, so freeing the table is enough: the
	// round becomes available and the phone starts on its own. No reload, and
	// nothing for the table to do.
	await expect(phoneB.page.getByText('RECORDING', { exact: true })).toBeVisible({
		timeout: 30_000,
	})

	// --- and the salvaged half becomes a real transcript on its own ---
	const state = await waitForState(fixture.round_id, firstRecording as string, [
		'AUDIO_READY',
		'TRANSCRIBING',
		'TRANSCRIBED',
		'TRANSCRIPTION_FAILED',
	])
	expect(state, 'the dead phone’s audio was never assembled').not.toBe('UPLOAD_INCOMPLETE')

	// the facilitator can still see it: showing only the newest recording made
	// the half just rescued vanish from the Live tab
	const table = tableOne(fixture.round_id)
	expect(table.superseded_recordings.map((r) => r.id)).toContain(firstRecording)
	expect(table.recording?.id).not.toBe(firstRecording)

	await phoneB.context.close()
})
