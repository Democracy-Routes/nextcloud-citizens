// SPDX-License-Identifier: AGPL-3.0-or-later
import { beforeEach, expect, it, vi } from 'vitest'
import { recorderApi, RecorderApiError } from '../../frontend/src/recorder/api'
import { transferChunk } from '../../frontend/src/recorder/transfer'
import { sha256Blob, sha256Hex } from '../../frontend/src/recorder/sha'
import type { StoredChunk } from '../../frontend/src/recorder/idb'

vi.mock('../../frontend/src/recorder/api', async (original) => ({
	...await original<typeof import('../../frontend/src/recorder/api')>(),
	recorderApi: { uploadChunk: vi.fn(), partStatus: vi.fn(), uploadPart: vi.fn(), finalizeChunk: vi.fn() },
}))

async function chunk(bytes: number): Promise<StoredChunk> {
	const data = new Uint8Array(bytes)
	for (let start = 0; start < bytes; start += 1024 * 1024) {
		data.fill(7 + start / (1024 * 1024), start, Math.min(bytes, start + 1024 * 1024))
	}
	const blob = new Blob([data])
	return { key: 'rec:0', recordingId: 'rec', seq: 0, blob, sha256: await sha256Blob(blob),
		sizeBytes: blob.size, createdAt: 1, acked: false, attempts: 0 }
}
beforeEach(() => vi.resetAllMocks())

it('incremental hashing matches WebCrypto across part boundaries', async () => {
	const c = await chunk(3 * 1024 * 1024 + 37)
	expect(c.sha256).toBe(await sha256Hex(await c.blob.arrayBuffer()))
})

it('falls back after a 413 and sends bounded parts without changing the original chunk', async () => {
	const c = await chunk(2 * 1024 * 1024 + 3)
	vi.mocked(recorderApi.uploadChunk).mockRejectedValue(new RecorderApiError(413, 'too large'))
	vi.mocked(recorderApi.partStatus).mockResolvedValue({ part_bytes: 1024 * 1024, complete: false,
		chunk_sha256: null, total_bytes: null, parts: [] })
	vi.mocked(recorderApi.finalizeChunk).mockResolvedValue({ acknowledged: true, sha256: c.sha256, size_bytes: c.sizeBytes })
	await transferChunk('token', 'rec', c)
	const calls = vi.mocked(recorderApi.uploadPart).mock.calls
	expect(calls.map((a) => a[3])).toEqual([0, 1, 2])
	expect(calls.map((a) => a[7].size)).toEqual([1024 * 1024, 1024 * 1024, 3])
	expect(await sha256Blob(new Blob(calls.map((a) => a[7])))).toBe(c.sha256)
})

it('resumes an oversized chunk after a lost acknowledgement without resending stored parts', async () => {
	const c = await chunk(5 * 1024 * 1024 + 1)
	const received: { number: number; sha256: string }[] = []
	vi.mocked(recorderApi.partStatus).mockImplementation(async () => ({ part_bytes: 1024 * 1024,
		complete: false, chunk_sha256: c.sha256, total_bytes: c.sizeBytes, parts: [...received] }))
	vi.mocked(recorderApi.uploadPart).mockImplementation(async (...args) => {
		received.push({ number: args[3], sha256: args[6] })
		if (received.length === 2) throw new TypeError('network lost after receipt')
		return { acknowledged: true }
	})
	await expect(transferChunk('token', 'rec', c)).rejects.toThrow('network lost')
	vi.mocked(recorderApi.finalizeChunk).mockResolvedValue({ acknowledged: true, sha256: c.sha256, size_bytes: c.sizeBytes })
	await transferChunk('token', 'rec', c)
	expect(recorderApi.uploadChunk).not.toHaveBeenCalled()
	expect(received.map((p) => p.number)).toEqual([0, 1, 2, 3, 4, 5])
})

it.each([401, 403, 413, 422])('surfaces permanent rejection %i without an infinite retry', async (status) => {
	const c = await chunk(5 * 1024 * 1024 + 1)
	vi.mocked(recorderApi.partStatus).mockRejectedValue(new RecorderApiError(status, 'rejected'))
	await expect(transferChunk('token', 'rec', c)).rejects.toMatchObject({ status })
	expect(recorderApi.partStatus).toHaveBeenCalledTimes(1)
	expect(recorderApi.finalizeChunk).not.toHaveBeenCalled()
})

it('refuses conflicting server bytes', async () => {
	const c = await chunk(5 * 1024 * 1024 + 1)
	vi.mocked(recorderApi.partStatus).mockResolvedValue({ part_bytes: 1024 * 1024, complete: true,
		chunk_sha256: 'wrong', total_bytes: c.sizeBytes, parts: [] })
	await expect(transferChunk('token', 'rec', c)).rejects.toMatchObject({ status: 409 })
	expect(recorderApi.uploadPart).not.toHaveBeenCalled()
})
