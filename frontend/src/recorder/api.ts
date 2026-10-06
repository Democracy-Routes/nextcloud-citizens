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

export type CapabilityPurpose =
	| 'ADD_RECORDER_TO_TABLE'
	| 'ADD_TABLE'
	| 'REGISTER_PARTICIPANT'
	| 'FACILITATE_TABLE'

/** The session the facilitator is in, with its clock (services/facilitators.py). */
export interface FacilitatorRound {
	id: string
	position: number
	title: string
	question: string
	objective: string
	status: string
	duration_minutes: number
	started_at: string | null
	ends_at: string | null
	/** negative once the time is up; null when the session is not running */
	seconds_left: number | null
}

/** A piece of advice from the AI facilitator, for the facilitator to judge. */
export interface FacilitatorAdvice {
	id: string
	kind: string
	text: string
	created_at: string
}

/** Everything the facilitator's page shows, for one table. */
export interface FacilitatorStatus {
	assembly: AssemblyInfo
	assembly_closed: boolean
	table_number: number
	color_key: string
	round: FacilitatorRound | null
	rounds: Array<{ id: string; position: number; title: string; status: string }>
	consent: TableConsent
	participants: Array<{ label: string; name: string; recording_consent: boolean }>
	recorders: number
	messages: PhoneMessage[]
	help: HelpState | null
	/** anonymous speaking balance when the engine labels speakers; null otherwise */
	speaking: { voices: number; shares: number[]; largest_percent: number } | null
	advice: FacilitatorAdvice[]
	/** the AI facilitator at this table: effective level and the table's own override */
	ai_facilitator?: AiFacilitatorState
	capabilities: { live_speaking_balance: boolean; ai_facilitator: boolean }
}

export type AiLevel = 'off' | 'light' | 'normal' | 'active'

export interface AiFacilitatorState {
	level: AiLevel
	override: AiLevel | null
	assembly_level: AiLevel | null
	instance_level: AiLevel
	configured: boolean
}

export interface FacilitatorJoin extends FacilitatorStatus {
	facilitator_token: string
	expires_at: string
}

/** What a registration code is for, read on the participant's own phone. */
export interface RegisterNotice extends ConsentNotice {
	assembly: AssemblyInfo
	/** null for the assembly's pre-registration link: seated at the door by name */
	table_number: number | null
	color_key: string | null
}

/** A person who registered ahead and has no table yet (names only). */
export interface UnseatedParticipant {
	id: string
	label: string
	name: string
	recording_consent: boolean
}

export interface SelfRegisterResult {
	participant_token: string
	participant: { id: string; label: string; name: string }
	consent: { method: string; recording: boolean }
	table_number: number
	color_key: string
}

/** A participant's own page (services/consent.py participant_status). */
export interface ParticipantStatus {
	assembly: AssemblyInfo
	participant: { label: string; name: string }
	table_number: number | null
	color_key: string | null
	consent: {
		recording: boolean
		transcription: boolean
		analysis: boolean
		publication: boolean
		confirmed_at: string
	} | null
	report_available: boolean
	/** every session, with the table this person sat at (null: none) */
	rounds?: Array<{ id: string; position: number; title: string; status: string; table_number: number | null }>
	/** what this person already said about their table's summaries, by session id */
	validations?: Record<string, { verdict: 'LOOKS_RIGHT' | 'MISSING'; note: string }>
	/** where to go next: the first coming session with a seat for this person */
	next_table?: { round_position: number; round_title: string; table_number: number; color_key: string } | null
	contact: string
	controller: string
}

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
	/** the assembly's consent rule and this table's roster count (0.7) */
	consent?: TableConsent
}

/** What the organizer said to this table and the phone has not shown yet. */
export interface PhoneMessage {
	id: number
	kind: 'TIME_LEFT' | 'WRAP_UP' | 'PROMPT' | 'CUSTOM'
	/** already in the assembly's language */
	text: string
	/** the phone may vibrate once */
	sound: boolean
	created_at: string
	/** who is speaking; absent from a server before the facilitator (0.7) */
	author?: 'organizer' | 'facilitator' | 'ai'
}

export type HelpKind = 'TECHNICAL' | 'ORGANIZER' | 'PROCESS'

/** This table's hand, up or just acknowledged (services/help.py). */
export interface HelpState {
	id: string
	kind: HelpKind
	table_number: number
	slot: number
	created_at: string
	acknowledged_at: string | null
}

/** The assembly's consent rule and where this table stands under it. */
export interface TableConsent {
	mode: 'required' | 'optional'
	registered: number
	consenting: number
	can_record: boolean
}

/** The notice as the server rendered it, hashed as shown, with this table's
 * roster (names only, never email). */
export interface ConsentNotice {
	version: string
	language: string
	hash: string
	paragraphs: string[]
	/** the sentence the one acceptance box carries (the last paragraph);
	 * absent from a 0.7.0 server, where the catalogue's sentence is used */
	acceptance?: string
	mode: 'required' | 'optional'
	participants: Array<{ label: string; name: string; recording_consent: boolean }>
}

export interface ConsentActIn {
	name: string
	email: string
	notice_hash: string
	notice_read: boolean
	recording_consent: boolean
	transcription_consent: boolean
	analysis_consent: boolean
	publication_consent: boolean
}

export interface RegisterResult {
	participant: { id: string; label: string; name: string }
	consent: { method: string; recording: boolean }
	can_record: boolean
	table: TableConsent
}

export interface RecorderStatus {
	assembly: AssemblyInfo
	messages?: PhoneMessage[]
	/** absent from a server older than 0.7 */
	consent?: TableConsent
	/** null: no hand up; absent: a server older than 0.7 */
	help?: HelpState | null
	/** the AI facilitator at this table (absent before 0.7) */
	ai_facilitator?: AiFacilitatorState
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
		tables: Array<{
			table_number: number
			summary: string
			findings: PublishedFinding[]
			/** participants' word on the summary (0.7); null when nobody answered */
			validations?: { looks_right: number; missing: number } | null
		}>
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

/** A PDF behind a bearer. The URL is identical for every assembly — only the
 * token says which one — so a cached copy would be another session's report.
 * The server sends no-store; this is the second lock on that door. */
async function pdfOf(path: string, token: string): Promise<Blob> {
	const response = await fetch(appBase() + path, {
		headers: { Authorization: `Bearer ${token}` },
		cache: 'no-store',
	})
	if (!response.ok) throw new RecorderApiError(response.status, `HTTP ${response.status}`)
	return response.blob()
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

	/** The notice people read before registering, and who already has. */
	consentNotice: (token: string) =>
		request<ConsentNotice>('GET', '/api/v1/public/recorder/consent-notice', { token }),

	/** The door's "find your name": people registered ahead, no table yet. */
	searchParticipants: (token: string, q: string) =>
		request<UnseatedParticipant[]>(
			'GET',
			`/api/v1/public/recorder/participants/search?q=${encodeURIComponent(q)}`,
			{ token },
		),

	/** A pre-registered person sits down at this table. */
	seatParticipant: (token: string, participantId: string) =>
		request<{ participant: { id: string; label: string; name: string }; table: TableConsent }>(
			'POST',
			`/api/v1/public/recorder/participants/${participantId}/seat`,
			{ token },
		),

	/** One person registers at this table on the shared phone. */
	registerParticipant: (token: string, act: ConsentActIn) =>
		request<RegisterResult>('POST', '/api/v1/public/recorder/participants', { token, json: act }),

	/** A registration code's event, table and notice — on the person's own phone. */
	registerNotice: (token: string) =>
		request<RegisterNotice>('POST', '/api/v1/public/register/notice', { json: { token } }),

	/** Register at the code's table from one's own phone; returns the page's bearer. */
	registerSelf: (token: string, act: ConsentActIn) =>
		request<SelfRegisterResult>('POST', '/api/v1/public/register', { json: { ...act, token } }),

	participantStatus: (token: string) =>
		request<ParticipantStatus>('GET', '/api/v1/public/participant/status', { token }),

	participantReport: (token: string) =>
		request<PublishedReport>('GET', '/api/v1/public/participant/report', { token }),

	/** "Does this reflect your table?" — once the report is out. */
	validateSummary: (token: string, roundId: string, verdict: 'LOOKS_RIGHT' | 'MISSING', note = '') =>
		request<{ round_id: string; verdict: string; note: string }>('POST', '/api/v1/public/participant/validate', {
			token,
			json: { round_id: roundId, verdict, note },
		}),

	/** The table raises its hand; the Live tab shows it until acknowledged. */
	needHelp: (token: string, kind: HelpKind) =>
		request<HelpState>('POST', '/api/v1/public/recorder/help', { token, json: { kind } }),

	/** The phone has shown the organizer's message — the Live tab's "delivered". */
	messageSeen: (token: string, messageId: number) =>
		request<{ ok: boolean }>('POST', '/api/v1/public/recorder/messages/seen', {
			token,
			json: { message_id: messageId },
		}),

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

	reportPdf: (token: string) => pdfOf('/api/v1/public/recorder/report.pdf', token),

	/** The same report, through a participant's own bearer. */
	participantReportPdf: (token: string) => pdfOf('/api/v1/public/participant/report.pdf', token),

	/* ---- the facilitator's own phone (0.7) ---- */

	/** Redeem the table's FACILITATE_TABLE code: a bearer for one table's view. */
	facilitate: (token: string) =>
		request<FacilitatorJoin>('POST', '/api/v1/public/facilitate', { json: { token } }),

	facilitatorStatus: (token: string) =>
		request<FacilitatorStatus>('GET', '/api/v1/public/facilitator/status', { token }),

	facilitatorHeartbeat: (token: string) =>
		request<{ ok: boolean }>('POST', '/api/v1/public/facilitator/heartbeat', { token }),

	facilitatorLeave: (token: string) =>
		request<{ ok: boolean }>('POST', '/api/v1/public/facilitator/leave', { token }),

	facilitatorMessageSeen: (token: string, messageId: number) =>
		request<{ ok: boolean }>('POST', '/api/v1/public/facilitator/messages/seen', {
			token,
			json: { message_id: messageId },
		}),

	/** A prompt to this table's phones, labelled as the facilitator's. */
	facilitatorPrompt: (token: string, text: string) =>
		request<PhoneMessage>('POST', '/api/v1/public/facilitator/prompt', { token, json: { text } }),

	/** The table's hand, raised from the facilitator's phone. */
	facilitatorHelp: (token: string, kind: HelpKind) =>
		request<HelpState>('POST', '/api/v1/public/facilitator/help', { token, json: { kind } }),

	/** The AI facilitator's advice: judged on the facilitator's phone. */
	facilitatorAdviceDismiss: (token: string, interventionId: string) =>
		request<FacilitatorAdvice>('POST', `/api/v1/public/facilitator/advice/${interventionId}/dismiss`, { token }),
	facilitatorAdviceSend: (token: string, interventionId: string) =>
		request<FacilitatorAdvice>('POST', `/api/v1/public/facilitator/advice/${interventionId}/send`, { token }),
	facilitatorAdviceFeedback: (token: string, interventionId: string, helpful: boolean) =>
		request<{ intervention_id: string; helpful: boolean }>(
			'POST', `/api/v1/public/facilitator/advice/${interventionId}/feedback`, { token, json: { helpful } },
		),

	/** The table's own AI-facilitator switch ('default' follows the assembly). */
	setFacilitatorLevel: (token: string, level: AiLevel | 'default') =>
		request<AiFacilitatorState>('POST', '/api/v1/public/recorder/facilitator', { token, json: { level } }),

	/** 👍 / 👎 under an AI facilitator banner. */
	messageFeedback: (token: string, messageId: number, helpful: boolean) =>
		request<{ intervention_id: string; helpful: boolean }>(
			'POST', `/api/v1/public/recorder/messages/${messageId}/feedback`, { token, json: { helpful } },
		),

	/** A code for this table: register for consent, or add a recorder (this phone included). */
	facilitatorCode: (token: string, purpose: 'REGISTER_PARTICIPANT' | 'ADD_RECORDER_TO_TABLE') =>
		request<CapabilityCard>('POST', '/api/v1/public/facilitator/codes', { token, json: { purpose } }),
}
