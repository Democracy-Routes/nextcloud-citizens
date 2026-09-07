// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/*
 * IndexedDB persistence for the recorder. Chunks are written here BEFORE any
 * upload attempt — local storage is the source of truth (brief §17.3).
 */

const DB_NAME = 'citizens-recorder'
const DB_VERSION = 2

/** Does this recording match the assembly a scoped operation is asking about?
 *
 * No assemblyId (an unscoped call) matches everything. A recording with no
 * assemblyId of its own — written before that field existed — matches ONLY the
 * unscoped call, never a specific assembly: treating "unknown" as "belongs to
 * whoever asks" let it block or be deleted by any assembly's purge.
 */
export function belongsTo(recording: { assemblyId?: string }, assemblyId?: string): boolean {
	return !assemblyId || recording.assemblyId === assemblyId
}

export interface StoredRecording {
	recordingId: string
	/** Which assembly this audio belongs to.
	 *
	 * Optional because recordings stored before this existed have none. A phone
	 * is often a citizen's own, used at more than one assembly over time, and
	 * without this there is no way to tell whose audio is whose — so an old
	 * recording could hijack a later event's recovery screen, and clearing one
	 * assembly could delete another's. Absent means "unknown", and unknown is
	 * always treated as belonging to whoever is asking.
	 */
	assemblyId?: string
	roundId: string
	/** The table this audio was recorded at. Was written as 0 by every caller
	 * and read by nobody; it names the recovery download, which the current
	 * session cannot do correctly once a phone has moved between tables. */
	tableNumber: number
	mimeType: string
	startedAt: number
	finishedAt: number | null
	totalChunks: number | null
	serverComplete: boolean
}

export interface StoredChunk {
	key: string // `${recordingId}:${seq}`
	recordingId: string
	seq: number
	blob: Blob
	sha256: string
	sizeBytes: number
	createdAt: number
	acked: boolean
	attempts: number
}

let dbPromise: Promise<IDBDatabase> | null = null

function openDb(): Promise<IDBDatabase> {
	if (!dbPromise) {
		dbPromise = new Promise((resolve, reject) => {
			const request = indexedDB.open(DB_NAME, DB_VERSION)
			request.onupgradeneeded = () => {
				const db = request.result
				if (!db.objectStoreNames.contains('recordings')) {
					db.createObjectStore('recordings', { keyPath: 'recordingId' })
				}
				if (!db.objectStoreNames.contains('chunks')) {
					const store = db.createObjectStore('chunks', { keyPath: 'key' })
					store.createIndex('byRecording', 'recordingId', { unique: false })
				}
				if (!db.objectStoreNames.contains('logs')) {
					db.createObjectStore('logs', { autoIncrement: true })
				}
			}
			request.onsuccess = () => resolve(request.result)
			request.onerror = () => reject(request.error ?? new Error('IndexedDB open failed'))
		})
	}
	return dbPromise
}

function tx<T>(
	storeName: string,
	mode: IDBTransactionMode,
	run: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
	return openDb().then(
		(db) =>
			new Promise<T>((resolve, reject) => {
				const transaction = db.transaction(storeName, mode)
				const request = run(transaction.objectStore(storeName))
				request.onerror = () => reject(request.error ?? new Error('IndexedDB request failed'))
				if (mode === 'readwrite') {
					// request.onsuccess fires while the transaction is still
					// uncommitted; a commit-time abort (disk full, storage
					// eviction) after it meant a chunk was counted, logged as
					// saved, and shown as "safe" — and did not exist. A write
					// only counts once the transaction has actually committed.
					let result: T
					request.onsuccess = () => {
						result = request.result
					}
					transaction.oncomplete = () => resolve(result)
					transaction.onabort = () =>
						reject(transaction.error ?? new Error('IndexedDB transaction aborted'))
				} else {
					request.onsuccess = () => resolve(request.result)
				}
			}),
	)
}

export const idb = {
	async selfTest(): Promise<void> {
		await tx('recordings', 'readwrite', (store) =>
			store.put({
				recordingId: '__selftest__',
				roundId: '',
				tableNumber: 0,
				mimeType: '',
				startedAt: Date.now(),
				finishedAt: null,
				totalChunks: null,
				serverComplete: false,
			} satisfies StoredRecording),
		)
		await tx('recordings', 'readwrite', (store) => store.delete('__selftest__'))
	},

	putRecording: (recording: StoredRecording) =>
		tx('recordings', 'readwrite', (store) => store.put(recording)),

	getRecordings: () =>
		tx<StoredRecording[]>('recordings', 'readonly', (store) => store.getAll()),

	deleteRecording: (recordingId: string) =>
		tx('recordings', 'readwrite', (store) => store.delete(recordingId)),

	putChunk: (chunk: StoredChunk) => tx('chunks', 'readwrite', (store) => store.put(chunk)),

	chunksFor(recordingId: string): Promise<StoredChunk[]> {
		return openDb().then(
			(db) =>
				new Promise((resolve, reject) => {
					const store = db.transaction('chunks', 'readonly').objectStore('chunks')
					const request = store.index('byRecording').getAll(recordingId)
					request.onsuccess = () =>
						resolve((request.result as StoredChunk[]).sort((a, b) => a.seq - b.seq))
					request.onerror = () => reject(request.error ?? new Error('IndexedDB read failed'))
				}),
		)
	},

	async deleteChunksFor(recordingId: string): Promise<void> {
		const chunks = await this.chunksFor(recordingId)
		for (const chunk of chunks) {
			await tx('chunks', 'readwrite', (store) => store.delete(chunk.key))
		}
	},

	/** Recordings that were interrupted or not confirmed by the server. */
	/** How many recordings of this assembly are still on this phone.
	 *
	 * Reported on the heartbeat so an organizer clearing the table phones can
	 * see how far that actually reached, rather than assume it reached all of
	 * them. Lives here rather than beside the purge logic because it only
	 * reads storage — putting it there would make engine and purge import each
	 * other.
	 */
	async countFor(assemblyId?: string): Promise<number> {
		try {
			const all = await this.getRecordings()
			return all.filter(
				(r) => r.recordingId !== '__selftest__' && belongsTo(r, assemblyId),
			).length
		} catch {
			return 0
		}
	},

	/** Unsynced recordings this assembly may still need to recover.
	 *
	 * Scoped, because the recovery screen is shown before a phone can join:
	 * an unscoped scan meant a phone carrying audio from a previous assembly
	 * was diverted into recovering THAT before it could record this one.
	 *
	 * A legacy recording (no assemblyId) matches ONLY the unscoped call — see
	 * belongsTo. Treating it as "belongs to whoever asks" made one such record
	 * block every assembly's purge forever and let one assembly's clear delete
	 * another's audio; scoping it out of specific-assembly queries fixes both,
	 * while the no-arg boot recovery scan still finds it.
	 */
	async unfinishedRecordings(assemblyId?: string): Promise<StoredRecording[]> {
		const all = await this.getRecordings()
		return all.filter(
			(r) =>
				r.recordingId !== '__selftest__' && !r.serverComplete && belongsTo(r, assemblyId),
		)
	},
}

interface LogRecord {
	ts: number
	level: string
	event: string
	data?: Record<string, unknown>
}

export const logsDb = {
	append: (entry: LogRecord) => tx('logs', 'readwrite', (store) => store.add(entry)),

	take(limit: number): Promise<{ entries: LogRecord[]; lastKey: number }> {
		return openDb().then(
			(db) =>
				new Promise((resolve, reject) => {
					const store = db.transaction('logs', 'readonly').objectStore('logs')
					const entries: LogRecord[] = []
					let lastKey = -1
					const request = store.openCursor()
					request.onsuccess = () => {
						const cursor = request.result
						if (cursor && entries.length < limit) {
							entries.push(cursor.value as LogRecord)
							lastKey = cursor.key as number
							cursor.continue()
						} else {
							resolve({ entries, lastKey })
						}
					}
					request.onerror = () => reject(request.error ?? new Error('log read failed'))
				}),
		)
	},

	deleteUpTo: (lastKey: number) =>
		tx('logs', 'readwrite', (store) =>
			store.delete(IDBKeyRange.upperBound(lastKey)),
		),
}
