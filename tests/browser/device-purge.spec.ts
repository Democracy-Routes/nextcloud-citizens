/*
 * Clearing the assembly's audio off the table phones.
 *
 * Every recording is written to the phone's own storage before it is uploaded,
 * so at the end of an assembly each phone still holds its table's audio. When
 * the phones belong to citizens rather than the organisation, that means people
 * walk home with a recording of the discussion on them.
 *
 * The rule that makes it safe for a phone to act on this without asking its
 * owner: only audio the SERVER has confirmed is removed. That is what the
 * second test here is for, and it is the more important of the two.
 */
import { expect, test } from '@playwright/test'
import { CHUNK_MS, newPhone, organizerApi, seed } from './support/phone'

async function finishRecording(phone: Awaited<ReturnType<typeof newPhone>>): Promise<void> {
	await phone.page.getByRole('button', { name: 'Finish recording', exact: true }).click()
	await phone.page.getByRole('button', { name: 'Yes, finish and synchronize' }).click()
	await expect(phone.page.getByText('Recording synchronized')).toBeVisible({ timeout: 120_000 })
}

test('the organizer clears a phone that is still sitting on the finished screen', async ({ browser }) => {
	test.setTimeout(240_000)
	const fixture = seed()

	const phone = await newPhone(browser, fixture.token)
	await phone.record()
	await phone.page.waitForTimeout(CHUNK_MS * 3)
	await finishRecording(phone)
	expect(await phone.localChunks()).toBeGreaterThan(0)

	// the assembly is over
	const closed = organizerApi('POST', `/api/v1/assemblies/${fixture.assembly_id}/close`)
	expect(closed.status, JSON.stringify(closed.body)).toBe(200)
	const purge = organizerApi('POST', `/api/v1/assemblies/${fixture.assembly_id}/purge-device-audio`)
	expect(purge.status, JSON.stringify(purge.body)).toBe(200)

	// The phone has been open since the round began and never reloads — which
	// is exactly the phone this feature exists for, and the one that used to
	// never notice.
	await expect(phone.page.getByText('removed from this phone')).toBeVisible({ timeout: 60_000 })
	expect(await phone.localChunks(), 'the audio is still on the phone').toBe(0)

	await phone.context.close()
})

/*
 * Not tested here: a purge landing while a table is still recording.
 *
 * It cannot happen through the product's own workflow. Purging requires the
 * session to be closed, and closing ends the open round — so every phone
 * finishes and synchronises before the request can be made. An attempt to
 * write that test only proved the workflow: the phone finished, its audio was
 * confirmed, and the purge then correctly cleared it.
 *
 * The recorder still refuses to act while it holds anything the server has not
 * confirmed (see hasUnfinishedAudio), which covers the case that IS reachable:
 * a phone that was offline when the request arrived and still has chunks to
 * send. That, and the rule that only confirmed audio is ever removed, are
 * covered deterministically in tests/frontend/purge-local-audio.spec.ts.
 */
