// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
import { sha256 } from '@noble/hashes/sha2.js'

export async function sha256Blob(blob: Blob): Promise<string> {
	const hash = sha256.create()
	for (let offset = 0; offset < blob.size; offset += 1024 * 1024) {
		hash.update(new Uint8Array(await blob.slice(offset, offset + 1024 * 1024).arrayBuffer()))
	}
	return Array.from(hash.digest(), (byte) => byte.toString(16).padStart(2, '0')).join('')
}

export async function sha256Hex(data: ArrayBuffer): Promise<string> {
	const digest = await crypto.subtle.digest('SHA-256', data)
	return Array.from(new Uint8Array(digest))
		.map((byte) => byte.toString(16).padStart(2, '0'))
		.join('')
}
