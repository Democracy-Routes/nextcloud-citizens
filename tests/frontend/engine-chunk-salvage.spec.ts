// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * One failed local chunk write must not poison the whole recording.
 *
 * enqueueChunk consumed a sequence number before persisting and swallowed the
 * failure, so finish() declared a total_chunks counting a chunk that was never
 * stored. The server waited for it forever; the phone retried the impossible
 * resend for five minutes and then failed the whole round. The contiguous
 * prefix can be salvaged, but must never be declared the complete recording.
 */
import { describe, expect, it, vi } from 'vitest'

const putRecording = vi.fn().mockResolvedValue(undefined)
const stored: { recordingId: string; totalChunks: number | null; finishedAt: number | null } = {
	recordingId: 'rec-1',
	totalChunks: null,
	finishedAt: null,
}
// chunks 0,1,2 persisted; 3 lost to a storage failure; 4 persisted (a gap)
const persisted = [0, 1, 2, 4]

vi.mock('../../frontend/src/recorder/idb', () => ({
	idb: {
		getRecordings: vi.fn(async () => [stored]),
		putRecording: (r: typeof stored) => {
			Object.assign(stored, r)
			return putRecording(r)
		},
		chunksFor: vi.fn(async () => persisted.map((seq) => ({ seq, blob: new Blob(), sha256: '' }))),
	},
}))
vi.mock('../../frontend/src/recorder/logger', () => ({ clientLog: vi.fn() }))
vi.mock('../../frontend/src/recorder/sha', () => ({ sha256Hex: vi.fn() }))
vi.mock('../../frontend/src/recorder/api', () => ({
	recorderApi: {},
	RecorderApiError: class extends Error {},
}))

const { RecorderEngine } = await import('../../frontend/src/recorder/engine')

describe('finish() when a chunk was lost locally', () => {
	it('detects the contiguous prefix without hiding a missing chunk', async () => {
		const engine = new RecorderEngine()
		const priv = engine as unknown as {
			state: { recordingId: string }
			seq: number
			persistedPrefixLength: () => Promise<number>
		}
		priv.state.recordingId = 'rec-1'
		priv.seq = 5 // the engine handed out 0..4

		// 0,1,2 are contiguous from zero; 4 sits past the gap at 3
		expect(await priv.persistedPrefixLength()).toBe(3)
	})

	it('finish preserves the full declaration and flags the capture incomplete', async () => {
		const engine = new RecorderEngine()
		const priv = engine as unknown as {
			seq: number
			mediaRecorder: { onstop: (() => void) | null; stop(): void }
		}
		engine.state.recordingId = 'rec-1'
		priv.seq = 5
		priv.mediaRecorder = { onstop: null, stop() { this.onstop?.() } }
		await engine.finish()
		expect(stored.totalChunks).toBe(5)
		expect(stored).toHaveProperty('captureIncomplete', true)
		expect(engine.state.phase).toBe('failed')
	})
})
