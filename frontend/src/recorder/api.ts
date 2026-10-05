// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/* Recorder API client. The base URL is injected by the recorder HTML page. */

declare global {
	interface Window {
		__CITIZENS_RECORDER_BASE__?: string
	}
}

export interface RoundInfo {
	id: string
	position: number
	title: string
	question: string
	/** what the discussion should produce, when the organizer stated it */
	objective?: string | null
	duration_minutes: number
	status: string
	/** state of this table's healthy recording for the round, null if none */
	recorded_state?: string | null
	/** whether that recording is this phone's own. The state above is scoped
	 * to the TABLE, so without this a phone cannot tell its own recording from
	 * the one left behind by a device it replaced. */
	recorded_by_this_device?: boolean
	/** this table's AI summary for the round ('' until analysis lands) */
	table_summary?: string
}

export interface AssemblyInfo {
	id: string
	/** "session" when this is the container behind a standalone Session */
	kind?: 'assembly' | 'session'
	name: string
	language: string
	recording_mode: 'orchestrated' | 'independent' | 'plenary'
}

export type CapabilityPurpose = 'ADD_RECORDER_TO_TABLE' | 'ADD_TABLE'

/** What scanning a code made this phone — decided by the code, never here. */
export interface Joined {
	purpose: 'JOIN_TABLE' | CapabilityPurpose
	table_number: number
	color_key: string
	slot: number
	table_created: boolean
}

/** The table as a whole, for the status line: how many recorder phones it has
 * and which of them carries the live captions. */
export interface TableInfo {
	number: number
	color_key: string
	slot: number
	slot_label: string
	recorders: number
	live_source_slot: number | null
	live_source_label: string | null
}

/** What a code means, read without consuming it. */
export type CapabilityPeek =
	| { valid: false; reason: 'invalid' | 'consumed' }
	| {
		valid: true
		purpose: 'JOIN_TABLE' | CapabilityPurpose
		table_number: number | null
		color_key: string | null
		/** recorder phones the table already has */
		recorders: number
		assembly_id: string
	}

/** A code this phone made for the next phone (services/capabilities.py). */
export interface CapabilityCard {
	purpose: CapabilityPurpose
	url: string
	qr_svg: string
	expires_at: string
	table_number: number | null
	color_key: string | null
	round_id: string | null
}

/** What the table is told before recording — names and durations only. */
export interface DataHandling {
	stt_provider?: string
	stt_configured?: boolean
	stt_hosted?: boolean
	analysis_enabled?: boolean
	analysis_hosted?: boolean
	audio_retention_days?: number
}

export interface JoinResult {
	session_token: string
	expires_at: string
	assembly: AssemblyInfo
	data_handling?: DataHandling
	table_number: number
	/** the colour beside the number — a cue, never something to depend on;
	 * absent from a server older than 0.7 */
	table_color?: string
	/** which of the table's recorders this phone is (1 = the table's own code) */
	slot?: number
	joined?: Joined
	table?: TableInfo
	rounds: RoundInfo[]
	/** The organizer has asked the phones to delete their local copies. */
	purge_local_audio?: boolean
}

export interface RecorderStatus {
	assembly: AssemblyInfo
	report_available?: boolean
	/** the organizer closed the assembly (possibly mid-round): stop, don't advance */
	assembly_closed?: boolean
	data_handling?: DataHandling
	table_number: number
	table_color?: string
	slot?: number
	table?: TableInfo
	rounds: RoundInfo[]
	purge_local_audio?: boolean
}

export interface PublishedReport {
	assembly: {
		name: string
		description: string
		language: string
		participants: number
		expected_participants: number
		tables: number
	}
	method: string
	methodology_note: string
	published_at: string | null
	rounds: Array<{
		position: number
		title: string
		/** "Turno 1 — …": the server already localised it. */
		heading?: string
		question: string
		summary: string
		cross_table: PublishedFinding[]
		tables: Array<{ table_number: number; summary: string; findings: PublishedFinding[] }>
	}>
}

export interface PublishedFinding {
	id: string
	type: string
	title: string
	summary: string
	/** The finding type in the assembly's language ("Proposta"). */
	type_label?: string
	mentioned_table_count: number | null
	evidence: Array<{ speaker: string; timestamp: string; text: string }>
}

export interface RecordingStatus {
	audio_manifest_sha256?: string | null
	audio_manifest_bytes?: number | null
	audio_available?: boolean
	recording_id: string
	state: string
	received_chunks: number
	total_chunks: number | null
	missing_sequences: number[]
	error_code: string
	duration_seconds: number | null
}

// window.__CITIZENS_RECORDER_BASE__ ends in "/recorder"; the API lives beside it.
function appBase(): string {
	const recorderBase = window.__CITIZENS_RECORDER_BASE__ ?? '/recorder'
	return recorderBase.replace(/\/recorder$/, '')
}

export class RecorderApiError extends Error {
	status: number

	constructor(status: number, message: string) {
		super(message)
		this.status = status
	}
}

async function request<T>(
	method: string,
	path: string,
	options: {
		token?: string
		json?: unknown
		body?: BodyInit
		headers?: Record<string, string>
		/** let the request outlive the page — for the last log lines on pagehide */
		keepalive?: boolean
	} = {},
): Promise<T> {
	const headers: Record<string, string> = { ...options.headers }
	if (options.token) headers.Authorization = `Bearer ${options.token}`
	let body: BodyInit | undefined = options.body
	if (options.json !== undefined) {
		headers['Content-Type'] = 'application/json'
		body = JSON.stringify(options.json)
	}
	const response = await fetch(appBase() + path, {
		method, headers, body, ...(options.keepalive ? { keepalive: true } : {}),
	})
	if (!response.ok) {
		let detail = `HTTP ${response.status}`
		try {
			const data = await response.json()
			if (data && typeof data.detail === 'string') detail = data.detail
		} catch {
			/* not JSON */
		}
		throw new RecorderApiError(response.status, detail)
	}
	return (await response.json()) as T
}

export const recorderApi = {
	partStatus: (token: string, recordingId: string, seq: number) =>
		request<{ part_bytes: number; complete: boolean; chunk_sha256: string | null;
			total_bytes: number | null; parts: Array<{ number: number; sha256: string }> }>(
			'GET', `/api/v1/public/recorder/recordings/${recordingId}/chunks/${seq}/parts`, { token }),
	uploadPart: (token: string, recordingId: string, seq: number, part: number,
		totalBytes: number, chunkHash: string, partHash: string, blob: Blob, segment = 0) =>
		request<{ acknowledged: boolean }>('POST',
			`/api/v1/public/recorder/recordings/${recordingId}/chunks/${seq}/parts/${part}`, {
				token, body: blob, headers: { 'Content-Type': 'application/octet-stream',
					'X-Total-Bytes': String(totalBytes), 'X-Chunk-SHA256': chunkHash, 'X-Part-SHA256': partHash,
					'X-Chunk-Segment': String(segment) },
			}),
	finalizeChunk: (token: string, recordingId: string, seq: number, segment = 0) =>
		request<{ acknowledged: boolean; sha256: string; size_bytes: number }>('POST',
			`/api/v1/public/recorder/recordings/${recordingId}/chunks/${seq}/finalize`, {
				token, headers: { 'X-Chunk-Segment': String(segment) },
			}),
	join: (token: string) => request<JoinResult>('POST', '/api/v1/public/join', { json: { token } }),

	/** What a code would do if scanned, without scanning it — so the phone can
	 * warn about an accident before a single-use code is spent. */
	peekCapability: (token: string) =>
		request<CapabilityPeek>('POST', '/api/v1/public/capabilities/peek', { json: { token } }),

	status: (token: string) => request<RecorderStatus>('GET', '/api/v1/public/recorder/status', { token }),

	start: (token: string, roundId: string, mimeType: string) =>
		request<{ recording_id: string; state: string }>('POST', '/api/v1/public/recorder/start', {
			token,
			json: { round_id: roundId, mime_type: mimeType },
		}),

	uploadChunk: (token: string, recordingId: string, seq: number, blob: Blob, sha256: string, segment = 0) =>
		request<{ acknowledged: boolean; duplicate: boolean }>(
			'POST',
			`/api/v1/public/recorder/recordings/${recordingId}/chunks/${seq}`,
			{
				token,
				body: blob,
				headers: {
					'Content-Type': 'application/octet-stream',
					'X-Chunk-SHA256': sha256,
					'X-Chunk-Segment': String(segment),
				},
			},
		),

	complete: (token: string, recordingId: string, totalChunks: number) =>
		request<{ state: string; missing_sequences: number[] }>(
			'POST',
			`/api/v1/public/recorder/recordings/${recordingId}/complete`,
			{ token, json: { total_chunks: totalChunks } },
		),

	recordingStatus: (token: string, recordingId: string) =>
		request<RecordingStatus>('GET', `/api/v1/public/recorder/recordings/${recordingId}`, { token }),

	/** The room's shared join QR, for adding another phone (plenary only). */
	inviteQr: (token: string) =>
		request<{ available: boolean; url?: string; qr_svg?: string }>(
			'GET',
			'/api/v1/public/recorder/invite-qr',
			{ token },
		),

	liveTranscript: (token: string, recordingId: string) =>
		request<{
			active: boolean
			lines: Array<{ t: number; text: string; speaker?: number | null }>
			// why there are no captions: "capacity" (concurrency cap reached,
			// intentionally off on this phone), "error" (session failed,
			// cooling down before a retry) or "backup" (another recorder of
			// this table carries the captions). Absent when nothing is wrong.
			reason?: string
			live_source_slot?: number | null
			live_source_label?: string | null
		}>(
			'GET',
			`/api/v1/public/recorder/recordings/${recordingId}/live`,
			{ token },
		),

	/** A code for the next phone: add a recorder to this table, or add a new
	 * table. The code means exactly that; the phone that scans it does not
	 * choose. Short-lived and single-use. */
	createCapability: (token: string, purpose: CapabilityPurpose, roundId?: string | null) =>
		request<CapabilityCard>('POST', '/api/v1/public/recorder/capabilities', {
			token,
			json: { purpose, round_id: roundId ?? null },
		}),

	/** This phone takes over its table's live captions. */
	promoteLiveSource: (token: string, recordingId: string) =>
		request<{ recording_id: string; live_source: boolean; slot: number }>(
			'POST', '/api/v1/public/recorder/live-source', { token, json: { recording_id: recordingId } },
		),

	heartbeat: (
		token: string,
		payload: {
			recording_id?: string
			recording_active: boolean
			armed?: boolean
			local_chunks: number
			acked_chunks: number
			storage_ok: boolean
			storage_free_mb?: number
			/** 0–1, absent where the browser will not expose it */
			battery_level?: number
			/** how many recordings this phone still holds locally */
			local_recordings?: number
			/** whether the recorder page is in the foreground right now */
			visible?: boolean
			/** while recording: a chunk arrived recently and no interruption is
			 * being bridged; absent when not recording */
			capture_ok?: boolean
			/** whether the screen wake lock is held (false: unsupported, refused,
			 * or released — the phone may lock itself) */
			screen_awake?: boolean
		},
	) => request<{ ok: boolean }>('POST', '/api/v1/public/recorder/heartbeat', { token, json: payload }),

	shipLogs: (token: string, entries: unknown[]) =>
		request<{ accepted: number }>('POST', '/api/v1/public/recorder/logs', {
			token,
			json: { entries },
			keepalive: true,
		}),

	report: (token: string) =>
		request<PublishedReport>('GET', '/api/v1/public/recorder/report', { token }),

	async reportPdf(token: string): Promise<Blob> {
		const response = await fetch(appBase() + '/api/v1/public/recorder/report.pdf', {
			headers: { Authorization: `Bearer ${token}` },
			// This URL is identical for every assembly — only the bearer token
			// says which one — so a cached copy is another session's report.
			// The server sends no-store; this is the second lock on that door.
			cache: 'no-store',
		})
		if (!response.ok) throw new RecorderApiError(response.status, `HTTP ${response.status}`)
		return response.blob()
	},
}
