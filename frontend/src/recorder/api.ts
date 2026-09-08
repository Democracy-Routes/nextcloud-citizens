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
	name: string
	language: string
	recording_mode: 'orchestrated' | 'independent' | 'plenary'
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
	rounds: RoundInfo[]
	/** The organizer has asked the phones to delete their local copies. */
	purge_local_audio?: boolean
}

export interface RecorderStatus {
	assembly: AssemblyInfo
	report_available?: boolean
	data_handling?: DataHandling
	table_number: number
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
	mentioned_table_count: number | null
	evidence: Array<{ speaker: string; timestamp: string; text: string }>
}

export interface RecordingStatus {
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
	options: { token?: string; json?: unknown; body?: BodyInit; headers?: Record<string, string> } = {},
): Promise<T> {
	const headers: Record<string, string> = { ...options.headers }
	if (options.token) headers.Authorization = `Bearer ${options.token}`
	let body: BodyInit | undefined = options.body
	if (options.json !== undefined) {
		headers['Content-Type'] = 'application/json'
		body = JSON.stringify(options.json)
	}
	const response = await fetch(appBase() + path, { method, headers, body })
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
	join: (token: string) => request<JoinResult>('POST', '/api/v1/public/join', { json: { token } }),

	status: (token: string) => request<RecorderStatus>('GET', '/api/v1/public/recorder/status', { token }),

	start: (token: string, roundId: string, mimeType: string) =>
		request<{ recording_id: string; state: string }>('POST', '/api/v1/public/recorder/start', {
			token,
			json: { round_id: roundId, mime_type: mimeType },
		}),

	uploadChunk: (token: string, recordingId: string, seq: number, blob: Blob, sha256: string) =>
		request<{ acknowledged: boolean; duplicate: boolean }>(
			'POST',
			`/api/v1/public/recorder/recordings/${recordingId}/chunks/${seq}`,
			{
				token,
				body: blob,
				headers: { 'Content-Type': 'application/octet-stream', 'X-Chunk-SHA256': sha256 },
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
			// intentionally off on this phone) or "error" (session failed,
			// cooling down before a retry). Absent when nothing is wrong.
			reason?: string
		}>(
			'GET',
			`/api/v1/public/recorder/recordings/${recordingId}/live`,
			{ token },
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
		},
	) => request<{ ok: boolean }>('POST', '/api/v1/public/recorder/heartbeat', { token, json: payload }),

	shipLogs: (token: string, entries: unknown[]) =>
		request<{ accepted: number }>('POST', '/api/v1/public/recorder/logs', {
			token,
			json: { entries },
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
