// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
import type {
	Assembly,
	AssemblyCreated,
	AssemblyDetail,
	AssemblyProgress,
	AssemblyUpdate,
	FilesListing,
	Invite,
	InviteGenerated,
	Participant,
	ProvidersSummary,
	SttProvider,
	ReportData,
	Round,
	RoundFindings,
	RoundIn,
	RoundMonitor,
	Table,
	TranscriptData,
} from './types'

// Derive the ExApp base URL from our own <script src>, so the app works both
// through /apps/app_api/proxy/citizens/... and a /exapps/citizens rewrite.
function detectBase(): string {
	const current = document.currentScript as HTMLScriptElement | null
	const el =
		current && current.src
			? current
			: document.querySelector<HTMLScriptElement>('script[src*="citizens-main"]')
	if (el && el.src) {
		return el.src.replace(/\/js\/citizens-main\.js.*$/, '')
	}
	return '/exapps/citizens'
}

export const BASE = detectBase()

export class ApiError extends Error {
	status: number

	constructor(status: number, message: string) {
		super(message)
		this.status = status
	}
}

// Partial updates use PUT, never PATCH: AppAPI's proxy registers handlers for
// GET/POST/PUT/DELETE only, so a PATCH is answered 405 by Nextcloud's router
// and never reaches the app. tests/unit/test_proxy_verbs.py enforces this.
async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
	const response = await fetch(BASE + path, {
		method,
		headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
		body: body === undefined ? undefined : JSON.stringify(body),
		credentials: 'same-origin',
	})
	if (!response.ok) {
		let detail = `HTTP ${response.status}`
		try {
			const data = await response.json()
			if (data && typeof data.detail === 'string') detail = data.detail
		} catch {
			/* not JSON */
		}
		throw new ApiError(response.status, detail)
	}
	if (response.status === 204) return undefined as T
	return (await response.json()) as T
}

export const api = {
	listAssemblies: () => request<Assembly[]>('GET', '/api/v1/assemblies'),
	createAssembly: (data: {
		name: string
		description: string
		language: string
		recording_mode: 'orchestrated' | 'independent' | 'plenary'
		expected_participants: number
		default_table_count: number
		analysis_instructions: string
		rounds: RoundIn[]
	}) => request<AssemblyCreated>('POST', '/api/v1/assemblies', data),
	getAssembly: (id: string) => request<AssemblyDetail>('GET', `/api/v1/assemblies/${id}`),
	updateAssembly: (id: string, data: AssemblyUpdate) =>
		request<AssemblyDetail>('PUT', `/api/v1/assemblies/${id}`, data),
	deleteAssembly: (id: string) => request<void>('DELETE', `/api/v1/assemblies/${id}`),

	addRound: (assemblyId: string, data: RoundIn) =>
		request<Round>('POST', `/api/v1/assemblies/${assemblyId}/rounds`, data),
	updateRound: (roundId: string, data: Partial<RoundIn> & { position?: number }) =>
		request<Round>('PUT', `/api/v1/rounds/${roundId}`, data),
	deleteRound: (roundId: string) => request<void>('DELETE', `/api/v1/rounds/${roundId}`),

	listParticipants: (assemblyId: string) =>
		request<Participant[]>('GET', `/api/v1/assemblies/${assemblyId}/participants`),
	addParticipants: (assemblyId: string, participants: Array<Partial<Participant> & { label: string }>) =>
		request<Participant[]>('POST', `/api/v1/assemblies/${assemblyId}/participants`, { participants }),
	importCsv: (assemblyId: string, csv: string) =>
		request<Participant[]>('POST', `/api/v1/assemblies/${assemblyId}/participants/import-csv`, { csv }),
	deleteParticipant: (id: string) => request<void>('DELETE', `/api/v1/participants/${id}`),

	roundTables: (roundId: string) => request<Table[]>('GET', `/api/v1/rounds/${roundId}/tables`),
	randomize: (roundId: string) =>
		request<Table[]>('POST', `/api/v1/rounds/${roundId}/assignments/randomize`),
	copyPrevious: (roundId: string) =>
		request<Table[]>('POST', `/api/v1/rounds/${roundId}/assignments/copy-previous`),
	moveParticipant: (roundId: string, participantId: string, toTableId: string) =>
		request<Table[]>('POST', `/api/v1/rounds/${roundId}/assignments/move`, {
			participant_id: participantId,
			to_table_id: toTableId,
		}),

	adminPing: () => request<{ ok: boolean }>('GET', '/api/v1/admin/ping'),
	getProviders: () => request<ProvidersSummary>('GET', '/api/v1/admin/providers'),
	updateProviders: (payload: Record<string, unknown>) =>
		request<ProvidersSummary>('PUT', '/api/v1/admin/providers', payload),
	testProvider: (target: SttProvider | 'analysis', apiKey?: string, baseUrl?: string) =>
		request<{ ok: boolean; message: string }>('POST', '/api/v1/admin/providers/test', {
			target,
			api_key: apiKey,
			base_url: baseUrl,
		}),

	startRound: (roundId: string) => request<Round>('POST', `/api/v1/rounds/${roundId}/start`),
	endRound: (roundId: string) => request<Round>('POST', `/api/v1/rounds/${roundId}/end`),
	roundMonitor: (roundId: string) => request<RoundMonitor>('GET', `/api/v1/rounds/${roundId}/monitor`),
	roundFindings: (roundId: string) =>
		request<RoundFindings>('GET', `/api/v1/rounds/${roundId}/findings`),
	updateFinding: (findingId: string, payload: { status?: string; title?: string; summary?: string }) =>
		request<unknown>('PUT', `/api/v1/findings/${findingId}`, payload),
	approveDrafts: (roundId: string, tableNumber?: number) =>
		request<{ approved: number }>('POST', `/api/v1/rounds/${roundId}/findings/approve`, {
			table_number: tableNumber ?? null,
		}),
	requestAnalysis: (roundId: string, force = false) =>
		request<{ queued: number }>('POST', `/api/v1/rounds/${roundId}/analyze`, { force }),
	assemblyReport: (assemblyId: string, includeDrafts: boolean) =>
		request<ReportData>(
			'GET',
			`/api/v1/assemblies/${assemblyId}/report?include_drafts=${includeDrafts}`,
		),
	publishReport: (assemblyId: string) =>
		request<{ published_at: string }>('POST', `/api/v1/assemblies/${assemblyId}/report/publish`),
	unpublishReport: (assemblyId: string) =>
		request<void>('DELETE', `/api/v1/assemblies/${assemblyId}/report/publish`),
	closeSession: (assemblyId: string) =>
		request<{ closed_at: string; progress: AssemblyProgress }>(
			'POST',
			`/api/v1/assemblies/${assemblyId}/close`,
		),
	reopenSession: (assemblyId: string) =>
		request<void>('DELETE', `/api/v1/assemblies/${assemblyId}/close`),
	refreshFinalReport: (assemblyId: string) =>
		request<{ final_report_at: string }>('POST', `/api/v1/assemblies/${assemblyId}/report/refresh`),

	listFiles: (assemblyId: string) =>
		request<FilesListing>('GET', `/api/v1/assemblies/${assemblyId}/files`),
	deleteRecordingAudio: (recordingId: string) =>
		request<{ freed_bytes: number }>('DELETE', `/api/v1/recordings/${recordingId}/audio`),
	deleteAssemblyAudio: (assemblyId: string) =>
		request<{ recordings: number; freed_bytes: number }>(
			'DELETE',
			`/api/v1/assemblies/${assemblyId}/audio`,
		),
	deleteRecordingTranscript: (recordingId: string) =>
		request<{ deleted: boolean; retranscribable: boolean }>(
			'DELETE',
			`/api/v1/recordings/${recordingId}/transcript`,
		),
	deleteAssemblyTranscripts: (assemblyId: string) =>
		request<{ transcripts: number }>('DELETE', `/api/v1/assemblies/${assemblyId}/transcripts`),

	getTranscript: (recordingId: string) =>
		request<TranscriptData>('GET', `/api/v1/recordings/${recordingId}/transcript`),
	/** Ask the table phones to delete their local copies of this assembly.
	 *
	 * Reaches phones whose recorder is still open; the response reports how
	 * many are known to still hold audio, so the UI can say what was covered
	 * rather than claim it is done. */
	purgeDeviceAudio: (assemblyId: string) =>
		request<{
			requested_at: string
			devices: number
			cleared: number
			still_holding: number
			unknown: number
		}>('POST', `/api/v1/assemblies/${assemblyId}/purge-device-audio`),
	/** This table's phone is gone; release the table so another can take over.
	 *
	 * Finishes the recording with whatever audio arrived — usually most of the
	 * round — rather than leaving it for someone to salvage by hand later. */
	replaceDevice: (recordingId: string) =>
		request<{ state: string; assembling: boolean }>(
			'POST',
			`/api/v1/recordings/${recordingId}/replace-device`,
		),
	/** Try assembling a recording's audio again — the way out of a failure
	 * that left it stuck, once the disk has room. */
	retryAssembly: (recordingId: string) =>
		request<{ state: string }>('POST', `/api/v1/recordings/${recordingId}/assemble`),
	requestTranscription: (recordingId: string) =>
		request<{ queued: boolean }>('POST', `/api/v1/recordings/${recordingId}/transcribe`),
	deviceLogs: (assemblyId: string, tableNumber: number, tail = 200) =>
		request<{ session_id: string | null; lines: string[] }>(
			'GET',
			`/api/v1/assemblies/${assemblyId}/tables/${tableNumber}/device-logs?tail=${tail}`,
		),

	uploadLogo: (base64: string) =>
		request<void>('PUT', '/api/v1/admin/logo', { data: base64 }),
	deleteLogo: () => request<void>('DELETE', '/api/v1/admin/logo'),

	listInvites: (assemblyId: string) =>
		request<Invite[]>('GET', `/api/v1/assemblies/${assemblyId}/invites`),
	inviteLinks: (assemblyId: string) =>
		request<InviteGenerated[]>('GET', `/api/v1/assemblies/${assemblyId}/invites/links`),
	generateInvites: (assemblyId: string) =>
		request<InviteGenerated[]>('POST', `/api/v1/assemblies/${assemblyId}/invites/generate`),
	revokeInvites: (assemblyId: string) =>
		request<void>('POST', `/api/v1/assemblies/${assemblyId}/invites/revoke`),
}
