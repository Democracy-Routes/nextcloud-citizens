/*
 * Release-blocker offline tests (brief §56):
 *  - Test A: network loss during recording — recording continues locally,
 *    everything synchronizes after reconnection, server reconstructs audio.
 *  - Test C: browser reload — persisted chunks are recovered and synchronized.
 *
 * Runs against the throwaway instance from scripts/browser-test-env.sh
 * (fake microphone; 2-second chunks via ?chunkms=2000).
 */

import { expect, test, type Page } from '@playwright/test'
import { CHUNK_MS, newPhone, seed } from './support/phone'

test('Test A: network loss during recording, recovery after reconnect', async ({ browser }) => {
	const fixture = seed()
	const phone = await newPhone(browser, fixture.token)
	const { page, context } = phone
	await phone.record()

	// record online long enough for a few chunks to upload
	await page.waitForTimeout(CHUNK_MS * 3)

	// network dies mid-recording
	await context.setOffline(true)
	await expect(page.getByText('Network unavailable', { exact: false })).toBeVisible({
		timeout: 20_000,
	})

	// recording continues locally while offline
	const before = await phone.localChunks()
	await page.waitForTimeout(CHUNK_MS * 4)
	const after = await phone.localChunks()
	expect(after).toBeGreaterThan(before)

	// network returns; pending chunks drain
	await context.setOffline(false)

	// finish and synchronize
	await page.getByRole('button', { name: 'Finish recording', exact: true }).click()
	await page.getByRole('button', { name: 'Yes, finish and synchronize' }).click()
	await expect(page.getByText('Recording synchronized')).toBeVisible({ timeout: 90_000 })

	// server-side verification: complete, no missing chunks, audio validated
	const recording = await latestRecordingState(page)
	expect(recording.state).toBe('AUDIO_READY')
	expect(recording.received_chunks).toBe(recording.total_chunks)
	await context.close()
})

test('Test C: browser reload mid-recording; chunks recovered and synchronized', async ({ browser }) => {
	const fixture = seed()
	const phone = await newPhone(browser, fixture.token)
	const { page } = phone
	await phone.record()

	// persist several chunks, then simulate a crash/reload
	await page.waitForTimeout(CHUNK_MS * 4)
	await page.reload()

	// recovery screen appears with the persisted chunks
	await expect(page.getByText('Recovered recording')).toBeVisible({ timeout: 20_000 })
	await expect(page.getByText('Recovered recording fully synchronized', { exact: false })).toBeVisible({
		timeout: 90_000,
	})
	await page.getByRole('button', { name: 'Continue' }).click()
	await expect(page.getByText('Microphone test')).toBeVisible()

	const recording = await latestRecordingState(page)
	expect(recording.state).toBe('AUDIO_READY')
	expect(recording.received_chunks).toBe(recording.total_chunks)
	await phone.context.close()
})

async function latestRecordingState(
	page: Page,
): Promise<{ state: string; received_chunks: number; total_chunks: number }> {
	// the recorder session token survives in localStorage; reuse it for the status API
	return page.evaluate(async () => {
		const stored = JSON.parse(localStorage.getItem('citizens-recorder-session') ?? '{}')
		const recordings: Array<{ recordingId: string }> = await new Promise((resolve, reject) => {
			const open = indexedDB.open('citizens-recorder')
			open.onsuccess = () => {
				const request = open.result
					.transaction('recordings', 'readonly')
					.objectStore('recordings')
					.getAll()
				request.onsuccess = () => resolve(request.result)
				request.onerror = () => reject(request.error)
			}
		})
		const real = recordings.filter((r) => r.recordingId !== '__selftest__')
		const latest = real[real.length - 1]
		const response = await fetch(`/api/v1/public/recorder/recordings/${latest.recordingId}`, {
			headers: { Authorization: `Bearer ${stored.session_token}` },
		})
		return response.json()
	})
}
