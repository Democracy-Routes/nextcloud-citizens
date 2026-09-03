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
 * slow browser to start reading, short enough not to pin a large blob. */
const REVOKE_DELAY_MS = 30_000

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
