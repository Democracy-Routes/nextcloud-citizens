// SPDX-License-Identifier: AGPL-3.0-or-later
import { execFileSync } from 'node:child_process'
import { expect, test, type Page } from '@playwright/test'
import { CHUNK_MS, newPhone, organizerApi, seed } from './support/phone'

async function finish(page: Page) {
	await page.getByRole('button', { name: 'Finish recording', exact: true }).click()
	await page.getByRole('button', { name: 'Yes, finish and synchronize' }).click()
}

async function locallyVerified(page: Page): Promise<boolean> {
	return page.evaluate(() => new Promise<boolean>((resolve, reject) => {
		const open = indexedDB.open('citizens-recorder')
		open.onsuccess = () => {
			const request = open.result.transaction('recordings').objectStore('recordings').getAll()
			request.onsuccess = () => resolve(request.result.some((r) => r.serverComplete && r.verificationVersion === 1))
			request.onerror = () => reject(request.error)
		}
		open.onerror = () => reject(open.error)
	}))
}

test('part receipts survive network interruption, server restart, and browser reload', async ({ browser }) => {
	test.setTimeout(240_000)
	const fixture = seed()
	const phone = await newPhone(browser, fixture.token)
	let interrupt = true
	let firstPartUploads = 0
	await phone.page.route(/\/chunks\/\d+$/, (route) => route.fulfill({ status: 413, body: 'proxy limit' }))
	await phone.page.route(/\/chunks\/0\/parts\/0$/, async (route) => {
		firstPartUploads++
		await route.continue()
	})
	await phone.page.route(/\/chunks\/\d+\/finalize$/, (route) => interrupt ? route.abort() : route.continue())
	await phone.record()
	await expect.poll(() => firstPartUploads, { timeout: 20_000 }).toBeGreaterThan(0)
	await phone.page.waitForTimeout(CHUNK_MS * 2)
	await finish(phone.page)
	expect(await locallyVerified(phone.page)).toBe(false)
	const id = await phone.recordingId()
	execFileSync('docker', ['restart', 'citizens-browser-test'], { stdio: 'pipe', timeout: 30_000 })
	await expect.poll(async () => (await phone.page.request.get('/recorder.html').catch(() => null))?.status(),
		{ timeout: 30_000 }).toBe(200)
	interrupt = false
	await phone.page.reload()
	await expect(phone.page.getByText('Recovered recording fully synchronized', { exact: false })).toBeVisible({ timeout: 90_000 })
	expect(await phone.recordingId()).toBe(id)
	expect(await locallyVerified(phone.page)).toBe(true)
	expect(firstPartUploads).toBe(1)
	expect(await phone.localChunks()).toBeGreaterThan(0)
	await phone.context.close()
})

test('revoked session keeps capturing, exposes local download, and resumes with a fresh matching QR', async ({ browser }) => {
	const fixture = seed()
	const phone = await newPhone(browser, fixture.token)
	await phone.record()
	await expect.poll(() => phone.localChunks(), { timeout: 20_000 }).toBeGreaterThan(0)
	const id = await phone.recordingId()
	expect(organizerApi('POST', `/api/v1/assemblies/${fixture.assembly_id}/invites/revoke`).status).toBe(204)
	await expect(phone.page.getByText('The server rejected the upload.', { exact: false })).toBeVisible({ timeout: 20_000 })
	const before = await phone.localChunks()
	await expect.poll(() => phone.localChunks(), { timeout: 20_000 }).toBeGreaterThan(before)
	await finish(phone.page)
	await phone.page.reload()
	await expect(phone.page.getByText('Scan a current QR code', { exact: false })).toBeVisible({ timeout: 20_000 })
	const download = phone.page.waitForEvent('download')
	await phone.page.getByRole('button', { name: 'Download audio file' }).click()
	expect((await download).suggestedFilename()).toContain(id!)
	expect(await phone.localChunks()).toBeGreaterThan(0)
	const invites = organizerApi<Array<{ table_number: number; url: string }>>('POST', `/api/v1/assemblies/${fixture.assembly_id}/invites/generate`)
	expect(invites.status).toBe(201)
	const token = invites.body.find((invite) => invite.table_number === 1)!.url.split('#/join/')[1]
	await phone.page.goto(`/recorder.html?chunkms=${CHUNK_MS}#/join/${token}`)
	await expect(phone.page.getByText('Recovered recording fully synchronized', { exact: false })).toBeVisible({ timeout: 90_000 })
	expect(await phone.recordingId()).toBe(id)
	expect(await locallyVerified(phone.page)).toBe(true)
	await phone.context.close()
})

test('two tables capture and verify concurrently without mixing recordings', async ({ browser }) => {
	const fixture = seed()
	const invites = organizerApi<Array<{ table_number: number; url: string }>>('POST', `/api/v1/assemblies/${fixture.assembly_id}/invites/generate`)
	expect(invites.status).toBe(201)
	const phones = await Promise.all(invites.body.map((invite) => newPhone(browser, invite.url.split('#/join/')[1])))
	expect(phones.length).toBe(2)
	await Promise.all(phones.map((phone) => phone.record()))
	await Promise.all(phones.map((phone) => expect.poll(() => phone.localChunks(), { timeout: 25_000 }).toBeGreaterThan(1)))
	await Promise.all(phones.map((phone) => finish(phone.page)))
	await Promise.all(phones.map((phone) => expect(phone.page.getByText('Recording synchronized')).toBeVisible({ timeout: 90_000 })))
	const ids = await Promise.all(phones.map((phone) => phone.recordingId()))
	expect(new Set(ids).size).toBe(2)
	for (const phone of phones) {
		expect(await locallyVerified(phone.page)).toBe(true)
		await phone.context.close()
	}
})
