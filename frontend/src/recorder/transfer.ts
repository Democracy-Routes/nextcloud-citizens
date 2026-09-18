// SPDX-License-Identifier: AGPL-3.0-or-later
import { RecorderApiError, recorderApi } from './api'
import { type StoredChunk } from './idb'
import { sha256Blob } from './sha'
import { t } from '../i18n'

const PART_BYTES = 1024 * 1024

export async function transferChunk(token: string, recordingId: string, chunk: StoredChunk): Promise<void> {
	if (chunk.blob.size <= 5 * 1024 * 1024) {
		try {
			await recorderApi.uploadChunk(token, recordingId, chunk.seq, chunk.blob, chunk.sha256)
			return
		} catch (error) {
			if (!(error instanceof RecorderApiError) || error.status !== 413) throw error
		}
	}
	const status = await recorderApi.partStatus(token, recordingId, chunk.seq)
	if (status.chunk_sha256 && (status.chunk_sha256 !== chunk.sha256 || status.total_bytes !== chunk.blob.size)) {
		throw new RecorderApiError(409, t('recorder.safety.unverified'))
	}
	if (status.complete) {
		if (status.chunk_sha256 !== chunk.sha256 || status.total_bytes !== chunk.blob.size) {
			throw new RecorderApiError(409, t('recorder.safety.unverified'))
		}
		return
	}
	const sendParts = async (force: boolean) => {
		for (let offset = 0, number = 0; offset < chunk.blob.size; offset += PART_BYTES, number++) {
			const blob = chunk.blob.slice(offset, offset + PART_BYTES)
			const hash = await sha256Blob(blob)
			if (!force && status.parts.some((p) => p.number === number && p.sha256 === hash)) continue
			await recorderApi.uploadPart(token, recordingId, chunk.seq, number,
				chunk.blob.size, chunk.sha256, hash, blob)
		}
	}
	await sendParts(false)
	let result
	try {
		result = await recorderApi.finalizeChunk(token, recordingId, chunk.seq)
	} catch (error) {
		if (!(error instanceof RecorderApiError) || error.status !== 409) throw error
		// Repair missing/damaged persisted parts once; do not loop on a conflict.
		await sendParts(true)
		result = await recorderApi.finalizeChunk(token, recordingId, chunk.seq)
	}
	if (result.sha256 !== chunk.sha256 || result.size_bytes !== chunk.blob.size) {
		throw new RecorderApiError(409, t('recorder.safety.unverified'))
	}
}
