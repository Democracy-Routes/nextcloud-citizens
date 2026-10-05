// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
export interface RoundIn {
	title: string
	question: string
	/** What the discussion should produce, as distinct from what it is about.
	 * Optional; null on every round made before 0.7. */
	objective?: string | null
	duration_minutes: number
}

export interface Round extends RoundIn {
	/** How many recordings this round would take with it if deleted. */
	recording_count?: number
	id: string
	position: number
	status: string
	started_at: string | null
	ended_at: string | null
}

export type RecordingMode = 'orchestrated' | 'independent' | 'plenary'

export interface Assembly {
	id: string
	/** "assembly" for an organized event; "session" for the container behind a
	 * standalone Session, which the UI lists as a Session and never as an
	 * assembly. Absent only from a server older than 0.7. */
	kind?: 'assembly' | 'session'
	/** the consent rule at the tables (0.7); absent from an older server */
	participant_consent?: ConsentMode
	/** Record now: the language follows the first transcript until chosen by hand */
	language_auto?: boolean
	name: string
	description: string
	language: string
	scheduled_at: string | null
	status: string
	recording_mode: 'orchestrated' | 'independent' | 'plenary'
	expected_participants: number
	default_table_count: number
	analysis_instructions: string
	auto_purge_device_audio: boolean
	redact_names: string
	closed_at: string | null
	created_by: string
	created_at: string
}

export interface AssemblyProgress {
	tables_expected: number
	tables_complete: number
	tables_contributed: number
	tables_missing: number[]
	rounds_total: number
	rounds_analyzed: number
	complete: boolean
}

/** The newest job behind a recording's state: why it failed, or how long it
 * is waiting. The runner always recorded this; nothing showed it. */
export interface JobInfo {
	state: string
	attempts: number
	max_attempts: number
	next_attempt_at: string | null
	failure_reason: string | null
	failure_detail: string | null
}

export interface FileEntry {
	recording_id: string
	table_number: number
	state: string
	/** Why it failed, when it did — a bare failed pill said nothing actionable. */
	error_code?: string
	job?: JobInfo | null
	updated_at?: string | null
	can_retry_assembly?: boolean
	mime_type: string
	duration_seconds: number | null
	size_bytes: number
	sha256: string
	created_at: string | null
	audio_available: boolean
	audio_deleted_at: string | null
	has_transcript: boolean
	transcript_source: string
	can_retranscribe: boolean
}

/** How far a request to clear the phones actually reached.
 *
 * Coverage, never completion: a phone closed and carried out of the building
 * never receives the request at all. */
export interface DeviceAudioCoverage {
	/** Recorder sessions, including older sessions; not distinct physical phones. */
	devices: number
	cleared: number
	still_holding: number
	unknown: number
}

export interface FilesListing {
	totals: {
		recordings: number
		audio_bytes: number
		audio_deleted: number
		/** audio the retention sweep refused to delete: no transcript exists,
		 * so for these recordings the audio is the only record */
		kept_past_retention: number
	}
	device_audio: DeviceAudioCoverage & {
		purge_requested_at: string | null
		auto_purge: boolean
	}
	rounds: Array<{ id: string; position: number; title: string; tables: FileEntry[] }>
}

/** Everything PUT /assemblies/{id} accepts. Every field is optional; only
 * what is sent is written. Was Record<string, unknown>, which typed nothing. */
export interface AssemblyUpdate {
	name?: string
	description?: string
	language?: string
	scheduled_at?: string | null
	recording_mode?: 'orchestrated' | 'independent' | 'plenary'
	expected_participants?: number
	default_table_count?: number
	analysis_instructions?: string
	auto_purge_device_audio?: boolean
	redact_names?: string
	audio_retention_days?: number | null
	participant_consent?: ConsentMode
	language_auto?: boolean
}

/** 'required': a table records only once one registered person there has
 * consented; 'optional': the notice is shown and registration offered,
 * nothing is blocked. */
export type ConsentMode = 'required' | 'optional'

export interface AssemblyDetail extends Assembly {
	rounds: Round[]
	participant_count: number
}

/** A person's newest consent act, as recorded at the table (0.7). */
export interface ParticipantConsent {
	method: 'TABLE_DEVICE' | 'SELF_PHONE' | 'PAPER' | string
	notice_version: string
	notice_hash: string
	notice_language: string
	notice_read: boolean
	recording: boolean
	transcription: boolean
	analysis: boolean
	publication: boolean
	confirmed_at: string
	withdrawn_at: string | null
}

export interface Participant {
	id: string
	label: string
	name: string
	email: string
	notes: string
	/** ORGANIZER (the list, the CSV), TABLE_DEVICE or SELF_PHONE; absent on older servers */
	source?: 'ORGANIZER' | 'TABLE_DEVICE' | 'SELF_PHONE' | string
	registered_table_number?: number | null
	consent?: ParticipantConsent | null
}

export type TableColor = 'blue' | 'green' | 'orange' | 'purple' | 'red' | 'teal'

export interface Table {
	id: string
	number: number
	/** a visual cue beside the number; derived from it, repeats after six */
	color_key?: TableColor | string
	label: string
	status: string
	participants: Participant[]
}

/** A table added while the event runs: the same number and colour in every
 * round, and the QR code that joins a phone to it (in this response only). */
export interface TableAdded {
	number: number
	color_key: TableColor | string
	invite: InviteGenerated
}

export interface Invite {
	id: string
	table_number: number
	active: boolean
	created_at: string
}

export interface InviteGenerated {
	table_number: number
	url: string
	qr_svg: string
}

export interface AssemblyCreated extends AssemblyDetail {
	invites: InviteGenerated[]
}

/** Start a Session: no assembly to describe first. */
export interface SessionCreate {
	question: string
	objective?: string | null
	duration_minutes: number
	table_count: number
	recording_mode: RecordingMode
	language: string
}

export interface SessionCreated {
	/** the Session's own id — what every /rounds/{id} route accepts */
	session_id: string
	/** the container the organizer screens are reached through */
	container_id: string
	question: string
	objective: string | null
	recording_mode: RecordingMode
	table_count: number
	invites: InviteGenerated[]
}

export interface RecordNowOut {
	session_id: string
	container_id: string
	table_number: number
	/** the recorder page with Table 1's join token: opening it on this device
	 * makes it the Session's recorder */
	recorder_url: string
}

export interface DeviceStatus {
	recording_active?: boolean
	armed?: boolean
	local_chunks?: number
	acked_chunks?: number
	storage_ok?: boolean
	storage_free_mb?: number
	/** 0–1. Absent means the browser would not say, NOT that the phone is fine:
	 * only Chromium exposes this. */
	battery_level?: number
	/** whether the recorder page is in the foreground; absent from older
	 * recorder builds */
	visible?: boolean
	/** while recording: whether audio is actually arriving from the
	 * microphone (false = the recorder went quiet and the phone is bridging
	 * an interruption); absent when not recording or from older builds */
	capture_ok?: boolean
	/** whether the phone holds a screen wake lock; false means the screen may
	 * switch off by itself (no API, refused, or released) */
	screen_awake?: boolean
}

export type ReadinessStatus = 'READY' | 'NEEDS_ATTENTION' | 'BLOCKED'

export type ReadinessCode =
	| 'NO_RECORDER'
	| 'RECORDER_OFFLINE'
	| 'MIC_UNAVAILABLE'
	| 'LOW_STORAGE'
	| 'LOW_BATTERY'
	| 'UPLOAD_STALLED'
	| 'LIVE_STT_UNAVAILABLE'

export interface TableReadiness {
	status: ReadinessStatus
	reasons: Array<{
		code: ReadinessCode | string
		severity: 'blocker' | 'warning'
		/** the recorder concerned, or null for the table as a whole */
		slot: number | null
		data: Record<string, unknown>
	}>
}

/** What the organizer said to the tables of a session, and who has shown it. */
export interface SessionMessage {
	id: number
	kind: 'TIME_LEFT' | 'WRAP_UP' | 'PROMPT' | 'CUSTOM'
	text: string
	sound: boolean
	created_at: string
	created_by: string | null
	/** null: every table */
	target_table_number: number | null
	seen_by: number[]
	not_seen_by: number[]
}

/** The assembly's pre-registration link, and how many used it (0.7). */
export interface RegistrationLink {
	url: string | null
	qr_svg: string | null
	expires_at: string | null
	registered: { total: number; seated: number }
}

/** A table's hand, up until the organizer acknowledges it. */
export interface HelpRequest {
	id: string
	kind: 'TECHNICAL' | 'ORGANIZER' | 'PROCESS'
	table_number: number
	slot: number
	created_at: string
	acknowledged_at: string | null
}

export interface MonitorTable {
	table_id: string
	number: number
	/** the table's open request for the organizer; absent on older servers */
	help_request?: HelpRequest | null
	color_key?: TableColor | string
	device: { connected: boolean; seconds_since_contact: number | null; status: DeviceStatus }
	armed: boolean
	local_recording_safe: boolean
	recording: {
		id: string
		state: string
		started_at: string | null
		received_chunks: number
		total_chunks: number | null
		error_code: string
		job?: JobInfo | null
	} | null
	/** Every recorder of the table, one per slot (A, B, …): the newest phone in
	 * that slot and its newest recording of this round. `device` and
	 * `recording` above keep describing the newest phone and recording overall;
	 * absent from a server older than 0.7. */
	recorders?: Array<{
		slot: number
		label: string
		connected: boolean
		seconds_since_contact: number | null
		status: DeviceStatus
		recording: { id: string; state: string } | null
	}>
	/** which recorder's captions the room reads; null when none */
	live_source_slot?: number | null
	/** Can this table record? Status plus reason codes, never prose — the
	 * client words them. Absent from a server older than 0.7. */
	readiness?: TableReadiness
	/** Recordings from a phone this table has since replaced. The server ships
	 * these so the salvaged half of a round stays visible while it finishes
	 * transcribing — otherwise it vanished from the Live tab the moment the
	 * replacement started. */
	superseded_recordings: Array<{
		id: string
		state: string
		error_code: string
		received_chunks: number
		job?: JobInfo | null
	}>
}

export type SttProvider = 'mistral' | 'deepgram' | 'whisper' | 'vosk'

export interface ProvidersSummary {
	organization_name: string
	audio_retention_days: number
	/** the organization data the consent notice prints (0.7) */
	consent_controller?: string
	consent_contact?: string
	org_address?: string
	org_dpo?: string
	org_hosting?: string
	org_authority?: string
	stt: {
		provider: SttProvider
		live_enabled: boolean
		batch_enabled: boolean
		mistral_configured: boolean
		mistral_key_hint: string
		mistral_live_model: string
		mistral_batch_model: string
		deepgram_configured: boolean
		deepgram_key_hint: string
		deepgram_live_model: string
		deepgram_batch_model: string
		deepgram_live_url: string
		whisper_configured: boolean
		whisper_key_hint: string
		whisper_base_url: string
		whisper_batch_model: string
		whisper_live_model: string
		vosk_url: string
		/** language code -> model NAME for captions and for the final transcript */
		vosk_language_models: Record<string, { live: string; final: string }>
		vosk_batch_model: string
		/** per-provider caps on concurrent transcription — live captions and
		 * final (batch) as independent pools, server-wide */
		stt_concurrency_deepgram_live: number
		stt_concurrency_deepgram_batch: number
		stt_concurrency_mistral_live: number
		stt_concurrency_mistral_batch: number
		stt_concurrency_vosk_live: number
		stt_concurrency_vosk_batch: number
		stt_concurrency_whisper_live: number
		stt_concurrency_whisper_batch: number
	}
	analysis: {
		base_url: string
		model: string
		configured: boolean
		key_hint: string
		enabled: boolean
		extra_instructions: string
		default_prompts?: { table: string; round: string }
	}
	logo_set: boolean
}

export interface TranscriptSegment {
	id: string
	speaker: string
	start: number
	end: number
	text: string
}

export interface TranscriptData {
	transcript_id: string
	recording_id: string
	provider: string
	model: string
	language: string
	segments: TranscriptSegment[]
}

export interface FindingEvidence {
	segment_id: string
	speaker: string
	start: number
	end: number
	text: string
}

export interface FindingData {
	id: string
	scope: 'table' | 'round'
	type: string
	title: string
	summary: string
	support: string
	status: string
	table_number: number | null
	mentioned_table_count: number
	ai_model: string
	reviewed_by: string | null
	evidence: FindingEvidence[]
}

export interface SpeakingVoice {
	label: string
	seconds: number
	percent: number
}

export interface SpeakingBalance {
	voices: SpeakingVoice[]
	total_seconds: number
	from_recording_id: string
	/** how many of the table's recordings held speech */
	parts?: number
	/** the balance covers only the fullest of several parts: voices cannot be
	 * matched across a replaced phone's recordings */
	recorder_changed?: boolean
}

/** One table of a session beside the others: voices, largest/smallest share, ratio. */
export interface SpeakingComparisonRow {
	table_number: number
	voices: number
	total_seconds: number
	largest_percent: number
	smallest_percent: number
	ratio: number | null
	recorder_changed: boolean
}

export interface RoundFindings {
	round_id: string
	round_status: string
	round_summary: string
	analysis_configured: boolean
	tables_with_findings: number
	speaking_comparison?: SpeakingComparisonRow[]
	cross_table: FindingData[]
	tables: Array<{
		table_number: number
		recording: { id: string; state: string; error_code?: string; job?: JobInfo | null } | null
		summary: string
		analyzed: boolean
		/** talk-time per detected voice at THIS table (never across tables) */
		speaking_balance?: SpeakingBalance | null
		findings: FindingData[]
	}>
	/** The newest cross-table clustering job, whatever its state. */
	round_job?: JobInfo | null
}

/** How the discussion developed across sessions (0.7). */
export interface ReportSynthesis {
	narrative: string
	stages: Array<{ title: string; summary: string }>
	carried_forward: string[]
	model?: string
	sessions?: number
	generated_at?: string | null
}

export interface ReportData {
	/** present once the analysis model has written it; null before */
	synthesis?: ReportSynthesis | null
	assembly: {
		name: string
		description: string
		language: string
		status: string
		participants: number
		expected_participants: number
		tables: number
	}
	method: string
	methodology_note: string
	include_drafts: boolean
	published_at: string | null
	closed_at: string | null
	is_final: boolean
	progress: AssemblyProgress
	rounds: Array<{
		position: number
		title: string
		/** "Round 1 — …" in the assembly's language; rendered as-is. */
		heading?: string
		question: string
		status: string
		summary: string
		recordings: number
		cross_table: ReportFinding[]
		tables: Array<{
			table_number: number
			summary: string
			speaking_balance?: SpeakingBalance | null
			findings: ReportFinding[]
			/** participants' word on the summary (0.7): counts, notes for the organizer */
			validations?: { looks_right: number; missing: number; notes?: string[] } | null
		}>
	}>
}

export interface ReportFinding {
	id: string
	type: string
	/** The type's label in the assembly's language ("Proposta"), from the server. */
	type_label?: string
	title: string
	summary: string
	support: string
	status: string
	is_draft: boolean
	table_number: number | null
	mentioned_table_count: number
	evidence_removed?: boolean
	evidence: Array<{ speaker: string; start: number; timestamp: string; text: string }>
}

export interface RoundMonitor {
	round_id: string
	status: string
	started_at: string | null
	duration_minutes: number
	recording_mode: 'orchestrated' | 'independent' | 'plenary'
	tables_ready: number
	tables_total: number
	tables: MonitorTable[]
	/** READY / NEEDS_ATTENTION / BLOCKED counts and the worst of them */
	readiness?: { status: ReadinessStatus; ready: number; needs_attention: number; blocked: number }
	/** Every round of the assembly, as the server has them right now. The Live
	 * tab used to read these from the assembly prop, which nothing refreshed. */
	rounds: { id: string; position: number; title: string; status: string }[]
}
