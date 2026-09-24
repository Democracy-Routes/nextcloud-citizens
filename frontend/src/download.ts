// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Saving a generated file to the user's device.
 *
 * Two details make the difference between this working and silently doing
 * nothing, and both were got wrong in one of the three places that used to
 * implement it by hand:
 *
 *  - the anchor must be IN the document when it is clicked;
 *  - the object URL must not be revoked synchronously afterwards. Firefox and
 *    Safari start the download asynchronously, so revoking on the next line
 *    cancels it before it begins.
 */

/** How long the object URL is kept alive after the click. Long enough for a
 * browser that asks "Download this file?" first and a person who reads the
 * question — iOS does, and 30 s was not — short enough not to pin a large
 * blob forever. */
export const REVOKE_DELAY_MS = 600_000

export function downloadBlob(blob: Blob, filename: string): void {
	const url = URL.createObjectURL(blob)
	const anchor = document.createElement('a')
	anchor.href = url
	anchor.download = filename
	document.body.appendChild(anchor)
	anchor.click()
	anchor.remove()
	window.setTimeout(() => URL.revokeObjectURL(url), REVOKE_DELAY_MS)
}

export type SaveOutcome = 'shared' | 'downloaded' | 'cancelled'

/** Can this browser hand a file to the operating system's share sheet? */
export function canShareFiles(file: File): boolean {
	return (
		typeof navigator.share === 'function' &&
		typeof navigator.canShare === 'function' &&
		navigator.canShare({ files: [file] })
	)
}

/** Save a file the way this device actually can.
 *
 * On an iPhone the anchor above is not a download. Safari NAVIGATES the tab
 * to the blob: URL; navigating away unloads the page that created the URL,
 * which revokes it, and the tab lands on "Safari cannot open the page
 * (WebKitBlobResource error 1)". At the 24 September 2026 rehearsal that
 * killed a recorder page that was still uploading, and the table's last
 * chunk never arrived. Where the browser can share files (iOS 15+, Android
 * Chrome) the share sheet — "Save to Files", AirDrop… — is how a phone
 * saves a file, and it never leaves the page. The anchor stays for
 * desktops, which have no share sheet.
 *
 * Must be called from a user gesture: the share sheet needs transient
 * activation, so a caller with data to fetch first should fetch it before
 * the tap, not after. Resolves 'cancelled' when the person dismissed the
 * sheet. Throws when a device that CAN share refused to — falling back to
 * the anchor there would be the navigation this exists to avoid.
 */
export async function saveBlob(blob: Blob, filename: string): Promise<SaveOutcome> {
	const file = new File([blob], filename, { type: blob.type })
	if (canShareFiles(file)) {
		try {
			await navigator.share({ files: [file], title: filename })
			return 'shared'
		} catch (error) {
			// a DOMException is not an Error in every runtime; the name is what matters
			if ((error as { name?: string } | null)?.name === 'AbortError') return 'cancelled'
			throw error
		}
	}
	downloadBlob(blob, filename)
	return 'downloaded'
}

/** The name the server asked us to save the file under.
 *
 * Several endpoints already build a careful filename — the audio export is
 * named after the assembly, round and table — so a caller with no better idea
 * should use that rather than inventing a worse one that will drift from it.
 */
function serverFilename(response: Response): string {
	const header = response.headers.get('content-disposition') ?? ''
	// RFC 5987 form first: it is the one that survives non-ASCII assembly names
	const encoded = header.match(/filename\*=UTF-8''([^;]+)/i)
	if (encoded) {
		try {
			return decodeURIComponent(encoded[1])
		} catch {
			/* malformed percent-encoding: fall through to the plain form */
		}
	}
	return header.match(/filename="?([^";]+)"?/i)?.[1] ?? 'download'
}

/** Fetch a file and save it, rather than navigating to it.
 *
 * Preferred over window.open for anything the user asked to download: a popup
 * blocker silently swallows the new tab, and the caller never finds out. This
 * throws instead, so the UI can say something.
 *
 * Omit the filename to keep the one the server sent.
 */
export async function downloadFromApi(url: string, filename?: string): Promise<void> {
	const response = await fetch(url, { credentials: 'same-origin' })
	if (!response.ok) throw new Error(`HTTP ${response.status}`)
	downloadBlob(await response.blob(), filename ?? serverFilename(response))
}
