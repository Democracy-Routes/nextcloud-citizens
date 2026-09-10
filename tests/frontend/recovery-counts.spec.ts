// SPDX-License-Identifier: AGPL-3.0-or-later
import { afterEach, expect, it, vi } from 'vitest'
import { RecorderEngine } from '../../frontend/src/recorder/engine'
import { idb, type StoredRecording } from '../../frontend/src/recorder/idb'
import { recorderApi, RecorderApiError } from '../../frontend/src/recorder/api'

vi.mock('../../frontend/src/recorder/logger', () => ({ clientLog: vi.fn() }))
afterEach(() => vi.restoreAllMocks())

it('an unreadable local store is unknown, not empty', async () => {
	vi.spyOn(idb, 'getRecordings').mockRejectedValue(new Error('storage unavailable'))
	expect(await idb.countFor('a1')).toBeUndefined()
})

it.each(['a1', undefined])('recovery counts only the known original assembly (%s)', async (assemblyId) => {
	const meta: StoredRecording = { recordingId: 'rec', assemblyId, roundId: 'round', tableNumber: 1,
		mimeType: 'audio/webm', startedAt: 1, finishedAt: 2, totalChunks: 1, serverComplete: false }
	vi.spyOn(idb, 'chunksFor').mockResolvedValue([])
	vi.spyOn(idb, 'countFor').mockResolvedValue(2)
	const heartbeat = vi.spyOn(recorderApi, 'heartbeat').mockResolvedValue({} as never)
	vi.spyOn(recorderApi, 'complete').mockRejectedValue(new RecorderApiError(401, 'expired'))
	const engine = new RecorderEngine()
	await engine.resumeSync('token', meta)
	await (engine as unknown as { sendHeartbeat(): Promise<void> }).sendHeartbeat()
	engine.stop()
	expect(heartbeat).toHaveBeenCalledWith('token', expect.objectContaining({ local_recordings: assemblyId ? 2 : undefined }))
	if (assemblyId) expect(idb.countFor).toHaveBeenCalledWith('a1')
	else expect(idb.countFor).not.toHaveBeenCalled()
})
