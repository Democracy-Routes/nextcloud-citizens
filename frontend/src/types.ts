// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
export interface RoundIn {
	title: string
	question: string
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

export interface Assembly {
	id: string
	name: string
	description: string
	language: string
	scheduled_at: string | null
	status: string
	recording_mode: 'orchestrated' | 'independent'
	expected_participants: number
	default_table_count: number
	analysis_instructions: string
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

export interface FileEntry {
	recording_id: string
	table_number: number
	state: string
	/** Why it failed, when it did — a bare failed pill said nothing actionable. */
	error_code?: string
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

export interface FilesListing {
	totals: { recordings: number; audio_bytes: number; audio_deleted: number }
	rounds: Array<{ id: string; position: number; title: string; tables: FileEntry[] }>
}

export interface AssemblyDetail extends Assembly {
	rounds: Round[]
	participant_count: number
}

export interface Participant {
	id: string
	label: string
	name: string
	email: string
	notes: string
}

export interface Table {
	id: string
	number: number
	label: string
	status: string
	participants: Participant[]
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

export interface DeviceStatus {
	recording_active?: boolean
	armed?: boolean
	local_chunks?: number
	acked_chunks?: number
	storage_ok?: boolean
	storage_free_mb?: number
}

export interface MonitorTable {
	table_id: string
	number: number
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
	} | null
}

export type SttProvider = 'mistral' | 'deepgram' | 'whisper' | 'vosk'

export interface ProvidersSummary {
	organization_name: string
	audio_retention_days: number
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

export interface RoundFindings {
	round_id: string
	round_status: string
	round_summary: string
	analysis_configured: boolean
	tables_with_findings: number
	cross_table: FindingData[]
	tables: Array<{
		table_number: number
		recording: { id: string; state: string } | null
		summary: string
		analyzed: boolean
		findings: FindingData[]
	}>
}

export interface ReportData {
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
		question: string
		status: string
		summary: string
		recordings: number
		cross_table: ReportFinding[]
		tables: Array<{ table_number: number; summary: string; findings: ReportFinding[] }>
	}>
}

export interface ReportFinding {
	id: string
	type: string
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
	recording_mode: 'orchestrated' | 'independent'
	tables_ready: number
	tables_total: number
	tables: MonitorTable[]
	/** Every round of the assembly, as the server has them right now. The Live
	 * tab used to read these from the assembly prop, which nothing refreshed. */
	rounds: { id: string; position: number; title: string; status: string }[]
}
