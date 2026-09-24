// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Saving a file must actually save it.
 *
 * The report tab's JSON export revoked the object URL on the line after
 * click(), and never put the anchor in the document. Chrome tolerates both;
 * Firefox and Safari start the download asynchronously, so revoking
 * immediately cancels it — the button did nothing at all, with no error.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { REVOKE_DELAY_MS, downloadBlob, downloadFromApi, saveBlob } from '../../frontend/src/download'

afterEach(() => {
	vi.restoreAllMocks()
	vi.unstubAllGlobals()
	vi.useRealTimers()
	delete (navigator as { share?: unknown }).share
	delete (navigator as { canShare?: unknown }).canShare
})

describe('downloadBlob', () => {
	it('clicks an anchor that is attached to the document', () => {
		let attachedAtClickTime = false
		const created = document.createElement('a')
		vi.spyOn(document, 'createElement').mockReturnValue(created)
		vi.spyOn(created, 'click').mockImplementation(() => {
			attachedAtClickTime = document.body.contains(created)
		})
		vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:x')
		vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)

		downloadBlob(new Blob(['hello']), 'notes.txt')

		expect(attachedAtClickTime).toBe(true)
	})

	it('does not revoke the object URL synchronously', () => {
		vi.useFakeTimers()
		const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
		vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:x')

		downloadBlob(new Blob(['hello']), 'notes.txt')

		expect(revoke).not.toHaveBeenCalled()
		// iOS asks "Download this file?" first; 30 s was not enough for a
		// person to read the question, and a revoked URL fails the download
		vi.advanceTimersByTime(30_000)
		expect(revoke).not.toHaveBeenCalled()
		vi.advanceTimersByTime(REVOKE_DELAY_MS)
		expect(revoke).toHaveBeenCalledWith('blob:x')
	})

	it('sets the filename the caller asked for', () => {
		const created = document.createElement('a')
		vi.spyOn(document, 'createElement').mockReturnValue(created)
		vi.spyOn(created, 'click').mockImplementation(() => undefined)
		vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:x')
		vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)

		downloadBlob(new Blob(['x']), 'bologna-report.pdf')

		expect(created.download).toBe('bologna-report.pdf')
	})

	it('removes the anchor again so the page is not littered', () => {
		vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:x')
		vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
		const before = document.body.querySelectorAll('a').length

		downloadBlob(new Blob(['x']), 'a.txt')

		expect(document.body.querySelectorAll('a').length).toBe(before)
	})
})

/**
 * On an iPhone the anchor is not a download: Safari navigates the tab to the
 * blob URL, which unloads the page that owns it, which revokes it — "Safari
 * cannot open the page (WebKitBlobResource error 1)". At the 24 September
 * 2026 rehearsal that killed a recorder page mid-upload. Where the browser can
 * share files, the share sheet saves the file and never leaves the page.
 */
describe('saveBlob', () => {
	function shareSheet(share: (data: ShareData) => Promise<void>, can = true) {
		Object.defineProperty(navigator, 'share', { value: vi.fn(share), configurable: true, writable: true })
		Object.defineProperty(navigator, 'canShare', {
			value: vi.fn(() => can),
			configurable: true,
			writable: true,
		})
	}

	it('hands the file to the share sheet where the browser can share files', async () => {
		shareSheet(async () => undefined)
		const createUrl = vi.spyOn(URL, 'createObjectURL')

		const outcome = await saveBlob(new Blob(['audio'], { type: 'audio/mp4' }), 'table-3.m4a')

		expect(outcome).toBe('shared')
		const shared = (navigator.share as ReturnType<typeof vi.fn>).mock.calls[0][0] as ShareData
		expect(shared.files?.[0]).toBeInstanceOf(File)
		expect(shared.files?.[0].name).toBe('table-3.m4a')
		expect(shared.files?.[0].type).toBe('audio/mp4')
		expect(createUrl, 'no blob URL, so nothing for Safari to navigate to').not.toHaveBeenCalled()
	})

	it('reports a dismissed share sheet as cancelled, not as saved', async () => {
		shareSheet(async () => {
			throw new DOMException('The user cancelled', 'AbortError')
		})

		expect(await saveBlob(new Blob(['audio']), 'a.webm')).toBe('cancelled')
	})

	it('does not fall back to the anchor on a phone that can share but refused', async () => {
		// the fallback would be the navigation this function exists to avoid
		shareSheet(async () => {
			throw new DOMException('No activation', 'NotAllowedError')
		})
		const createUrl = vi.spyOn(URL, 'createObjectURL')

		await expect(saveBlob(new Blob(['audio']), 'a.webm')).rejects.toThrow('No activation')
		expect(createUrl).not.toHaveBeenCalled()
	})

	it('uses the anchor where files cannot be shared', async () => {
		shareSheet(async () => undefined, false)
		const created = document.createElement('a')
		vi.spyOn(document, 'createElement').mockReturnValue(created)
		const click = vi.spyOn(created, 'click').mockImplementation(() => undefined)
		vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:x')
		vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)

		expect(await saveBlob(new Blob(['audio']), 'a.webm')).toBe('downloaded')
		expect(click).toHaveBeenCalled()
		expect(navigator.share).not.toHaveBeenCalled()
	})

	it('uses the anchor where there is no share sheet at all', async () => {
		const created = document.createElement('a')
		vi.spyOn(document, 'createElement').mockReturnValue(created)
		const click = vi.spyOn(created, 'click').mockImplementation(() => undefined)
		vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:x')
		vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)

		expect(await saveBlob(new Blob(['audio']), 'a.webm')).toBe('downloaded')
		expect(click).toHaveBeenCalled()
	})
})

describe('downloadFromApi', () => {
	function respond(headers: Record<string, string>): void {
		vi.stubGlobal(
			'fetch',
			vi.fn().mockResolvedValue({
				ok: true,
				headers: new Headers(headers),
				blob: async () => new Blob(['x']),
			}),
		)
	}

	/** Capture the anchor downloadBlob builds, so we can read its filename. */
	function anchor(): HTMLAnchorElement {
		const created = document.createElement('a')
		vi.spyOn(document, 'createElement').mockReturnValue(created)
		vi.spyOn(created, 'click').mockImplementation(() => undefined)
		vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:x')
		vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
		return created
	}

	it('keeps the name the server chose when the caller gives none', async () => {
		// the audio and export endpoints already name these after the
		// assembly, round and table — inventing a name here would drift
		respond({ 'content-disposition': 'attachment; filename="bologna-round1-table3.webm"' })
		const link = anchor()

		await downloadFromApi('/api/v1/recordings/r1/audio')

		expect(link.download).toBe('bologna-round1-table3.webm')
	})

	it('reads the RFC 5987 form, so non-ASCII assembly names survive', async () => {
		respond({
			'content-disposition': "attachment; filename*=UTF-8''Bologna%20Citt%C3%A0-audio.zip",
		})
		const link = anchor()

		await downloadFromApi('/api/v1/assemblies/a1/audio.zip')

		expect(link.download).toBe('Bologna Città-audio.zip')
	})

	it('still lets the caller override the name', async () => {
		respond({ 'content-disposition': 'attachment; filename="server-name.pdf"' })
		const link = anchor()

		await downloadFromApi('/x', 'my-name.pdf')

		expect(link.download).toBe('my-name.pdf')
	})

	it('throws on a failed response, so the caller can say something', async () => {
		vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404 }))

		await expect(downloadFromApi('/missing')).rejects.toThrow('HTTP 404')
	})
})
