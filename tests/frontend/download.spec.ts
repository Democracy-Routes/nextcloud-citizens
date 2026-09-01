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
import { downloadBlob } from '../../frontend/src/download'

afterEach(() => {
	vi.restoreAllMocks()
	vi.useRealTimers()
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
		vi.advanceTimersByTime(30_000)
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
