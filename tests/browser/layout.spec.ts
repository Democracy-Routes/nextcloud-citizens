/*
 * The recorder is an app, not a page: on old, small phones the document never
 * scrolls vertically, the timer ring stays a modest part of the screen, and
 * the controls that matter (Finish, the level meter) are on screen while
 * recording. Only boxes inside the screen scroll.
 */
import { expect, test } from '@playwright/test'
import { newPhone, seed } from './support/phone'

for (const size of [
	{ width: 320, height: 568 },
	{ width: 360, height: 640 },
]) {
	test(`recording fits a ${size.width}x${size.height} phone without page scroll`, async ({ browser }) => {
		const fixture = seed()
		const phone = await newPhone(browser, fixture.token)
		const { page } = phone
		await page.setViewportSize(size)
		await phone.record()
		await page.waitForTimeout(1500)

		const noPageScroll = async () =>
			page.evaluate(() => {
				const el = document.scrollingElement as HTMLElement
				return el.scrollHeight - window.innerHeight
			})
		expect(await noPageScroll()).toBeLessThanOrEqual(1)

		const inViewport = async (selector: string) => {
			const box = await page.locator(selector).first().boundingBox()
			expect(box, `${selector} has no box`).not.toBeNull()
			expect(box!.y).toBeGreaterThanOrEqual(0)
			expect(box!.y + box!.height).toBeLessThanOrEqual(size.height + 1)
			return box!
		}

		const finish = page.getByRole('button', { name: 'Finish recording', exact: true })
		await expect(finish).toBeVisible()
		const finishBox = (await finish.boundingBox())!
		expect(finishBox.y).toBeGreaterThanOrEqual(0)
		expect(finishBox.y + finishBox.height).toBeLessThanOrEqual(size.height + 1)

		await inViewport('.rc-level')
		await inViewport('.rc-techbar')
		const ring = await inViewport('.rc-timer-ring')
		expect(ring.height).toBeLessThanOrEqual(size.height * 0.4)

		// opening the finish confirmation must not make the page scroll either
		await finish.click()
		await expect(page.getByRole('button', { name: 'Yes, finish and synchronize' })).toBeVisible()
		expect(await noPageScroll()).toBeLessThanOrEqual(1)

		await phone.context.close()
	})
}
