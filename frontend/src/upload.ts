// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Sending a whole file to the server in parts.
 *
 * Every request body through the AppAPI proxy is capped at a few megabytes
 * (citizens/api/limits.py), and a session export or a table's audio is far
 * bigger. So the organizer page never posts a file in one go: it opens an
 * upload, sends 5 MB parts one after another, and closes it with the hash of
 * the whole file, which the server checks before anything reads the bytes.
 * The upload id then names the file to the route that consumes it (import a
 * session, attach a transcript, attach audio).
 */

import { api, type UploadKind } from './api'

export interface UploadedFile {
	upload_id: string
	size_bytes: number
	sha256: string
}

async function sha256Hex(file: File): Promise<string> {
	const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer())
	return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join('')
}

/** Upload `file` in parts; `onProgress` gets a fraction in [0, 1] after each
 * part lands. Throws ApiError from the first request that fails; the server
 * forgets an unfinished upload on its own after a day. */
export async function uploadFile(
	file: File,
	kind: UploadKind,
	onProgress?: (fraction: number) => void,
): Promise<UploadedFile> {
	const opened = await api.beginUpload({ kind, filename: file.name, size_bytes: file.size })
	const partBytes = opened.part_bytes
	let sent = 0
	for (let index = 0; index < opened.parts; index += 1) {
		const part = file.slice(index * partBytes, Math.min(file.size, (index + 1) * partBytes))
		await api.uploadPart(opened.upload_id, index, part)
		sent += part.size
		onProgress?.(file.size === 0 ? 1 : sent / file.size)
	}
	return api.completeUpload(opened.upload_id, await sha256Hex(file))
}
