// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
import type {
	AboutInfo,
	Account,
	AccountCreated,
	AuthConfig,
	Me,
	Intervention,
	Assembly,
	AssemblyCreated,
	AssemblyDetail,
	AssemblyProgress,
	AssemblyUpdate,
	DeviceReport,
	FilesListing,
	Invite,
	InviteGenerated,
	Participant,
	ProvidersSummary,
	VoskModelsResponse,
	RecordNowOut,
	SttProvider,
	ReportData,
	Round,
	RoundFindings,
	RoundIn,
	HelpRequest,
	RegistrationLink,
	RoundMonitor,
	SeedsListing,
	StatementSeed,
	SessionCreate,
	SessionCreated,
	SessionMessage,
	Table,
	TableAdded,
	TranscriptData,
} from './types'

// Derive the ExApp base URL from our own <script src>, so the app works both
// through /apps/app_api/proxy/citizens/... and a /exapps/citizens rewrite.
export function baseFromScriptSrc(src: string): string {
	return src.replace(/\/js\/citizens-main(\.bundle)?\.js.*$/, '')
}

function detectBase(): string {
	const current = document.currentScript as HTMLScriptElement | null
	const el =
		current && current.src
			? current
			: document.querySelector<HTMLScriptElement>('script[src*="citizens-main"]')
	if (el && el.src) {
		// Since 0.8 the registered `js/citizens-main.js` is a loader and the
		// code runs from `js/citizens-main.bundle.js?v=<version>`: both names
		// must strip, or the base is the bundle URL itself and every API call
		// downloads the bundle again (the "cannot be reached — JSON parse"
		// banner on the Home page after the 0.8 deploy).
		return baseFromScriptSrc(el.src)
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
// Standalone mode refuses an unsafe request that does not name its client
// (the cookie alone must not be enough for a cross-site form post), so every
// request carries the header in both modes; Nextcloud ignores it.
const CLIENT_HEADERS = { 'X-Citizens-Client': 'organizer' }

// An expired session in standalone mode: the shell registers a handler that
// brings the login view back. The sign-in calls themselves answer 401 for
// ordinary reasons (wrong password, signed out) and are exempt.
let unauthorizedHandler: (() => void) | null = null
export function setUnauthorizedHandler(handler: (() => void) | null): void {
	unauthorizedHandler = handler
}
const AUTH_EXEMPT = ['/api/v1/auth/login', '/api/v1/auth/me', '/api/v1/auth/set-password']

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
	const response = await fetch(BASE + path, {
		method,
		headers:
			body === undefined
				? { ...CLIENT_HEADERS }
				: { ...CLIENT_HEADERS, 'Content-Type': 'application/json' },
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
		if (response.status === 401 && unauthorizedHandler && !AUTH_EXEMPT.some((p) => path.startsWith(p))) {
			unauthorizedHandler()
		}
		throw new ApiError(response.status, detail)
	}
	if (response.status === 204) return undefined as T
	return (await response.json()) as T
}

export const api = {
	// ---- sign-in and accounts (standalone mode; config and me answer in both)
	authConfig: () => request<AuthConfig>('GET', '/api/v1/auth/config'),
	me: () => request<Me>('GET', '/api/v1/auth/me'),
	updateMe: (data: {
		display_name?: string
		language?: string
		current_password?: string
		password?: string
	}) => request<Account>('PUT', '/api/v1/auth/me', data),
	login: (data: { username: string; password: string }) =>
		request<Account>('POST', '/api/v1/auth/login', data),
	logout: () => request<void>('POST', '/api/v1/auth/logout'),
	requestReset: (email: string) => request<{ ok: boolean }>('POST', '/api/v1/auth/reset', { email }),
	setPassword: (data: { token: string; password: string }) =>
		request<Account>('POST', '/api/v1/auth/set-password', data),
	listUsers: () => request<{ users: Account[]; mail: boolean }>('GET', '/api/v1/admin/users'),
	createUser: (data: {
		username: string
		display_name: string
		email: string | null
		role: 'admin' | 'organizer'
		language: string
	}) => request<AccountCreated>('POST', '/api/v1/admin/users', data),
	updateUser: (
		id: string,
		data: {
			display_name?: string
			email?: string
			role?: 'admin' | 'organizer'
			language?: string
			disabled?: boolean
		},
	) => request<Account>('PUT', `/api/v1/admin/users/${id}`, data),
	inviteUser: (id: string) =>
		request<{ ok: boolean; mail: boolean }>('POST', `/api/v1/admin/users/${id}/invite`),
	deleteUser: (id: string) => request<void>('DELETE', `/api/v1/admin/users/${id}`),

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
		/** the organizer's wizard sends 'required'; the server defaults to 'optional' */
		participant_consent?: 'required' | 'optional'
		/** null: the instance default; 0: keep indefinitely */
		audio_retention_days?: number | null
		zero_retention?: boolean
	}) => request<AssemblyCreated>('POST', '/api/v1/assemblies', data),
	getAssembly: (id: string) => request<AssemblyDetail>('GET', `/api/v1/assemblies/${id}`),

	// A Session on its own: no assembly to name or configure first. The rows
	// behind it are reached through container_id on the assembly routes.
	createSession: (data: SessionCreate) => request<SessionCreated>('POST', '/api/v1/sessions', data),
	recordNow: (data: { language: string }) =>
		request<RecordNowOut>('POST', '/api/v1/sessions/record-now', data),
	// a standalone Session becomes an Assembly (an event of several sessions),
	// keeping everything it already has
	promoteSession: (sessionId: string, name: string) =>
		request<{ container_id: string; kind: string; name: string }>(
			'POST', `/api/v1/sessions/${sessionId}/promote`, { name },
		),
	updateAssembly: (id: string, data: AssemblyUpdate) =>
		request<AssemblyDetail>('PUT', `/api/v1/assemblies/${id}`, data),
	deleteAssembly: (id: string) => request<void>('DELETE', `/api/v1/assemblies/${id}`),
	/** Change the language after recording has begun (S8): the old PUT keeps
	 * refusing it once audio exists. Every recording with audio is queued to
	 * be transcribed again. 409 with detail SESSION_ACTIVE while a session is
	 * being recorded, or ZERO_RETENTION_APPLIED. */
	changeLanguage: (id: string, language: string) =>
		request<{ language: string; queued: number; skipped_no_audio: number; closed: boolean }>(
			'POST',
			`/api/v1/assemblies/${id}/language`,
			{ language },
		),

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
	/** Changed their mind / withdraws consent, recorded on the person's word (a further act). */
	participantConsent: (
		assemblyId: string,
		participantId: string,
		flags: { recording_consent: boolean; transcription_consent: boolean; analysis_consent: boolean; publication_consent: boolean },
	) =>
		request<{ participant: { id: string; label: string }; consent: unknown }>(
			'POST',
			`/api/v1/assemblies/${assemblyId}/participants/${participantId}/consent`,
			flags,
		),
	/** Moved to another table: leaves the current table's roster for the sessions still to come. */
	participantMoved: (assemblyId: string, participantId: string) =>
		request<{ participant: { id: string; label: string } }>(
			'POST',
			`/api/v1/assemblies/${assemblyId}/participants/${participantId}/moved`,
		),

	roundTables: (roundId: string) => request<Table[]>('GET', `/api/v1/rounds/${roundId}/tables`),
	// the next table, in every round at once, with its QR code (in this response only)
	addTable: (assemblyId: string) => request<TableAdded>('POST', `/api/v1/assemblies/${assemblyId}/tables`),
	randomize: (roundId: string) =>
		request<Table[]>('POST', `/api/v1/rounds/${roundId}/assignments/randomize`),
	copyPrevious: (roundId: string) =>
		request<Table[]>('POST', `/api/v1/rounds/${roundId}/assignments/copy-previous`),
	/** Seat everyone with a goal: meet new people, random, or continuity. */
	remix: (roundId: string, goal: 'new_people' | 'random' | 'continuity') =>
		request<{ goal: string; seated: number; repeated_pairs: number; tables: Table[] }>(
			'POST',
			`/api/v1/rounds/${roundId}/assignments/remix`,
			{ goal },
		),
	moveParticipant: (roundId: string, participantId: string, toTableId: string) =>
		request<Table[]>('POST', `/api/v1/rounds/${roundId}/assignments/move`, {
			participant_id: participantId,
			to_table_id: toTableId,
		}),

	adminPing: () => request<{ ok: boolean }>('GET', '/api/v1/admin/ping'),
	about: () => request<AboutInfo>('GET', '/api/v1/admin/about'),
	getProviders: () => request<ProvidersSummary>('GET', '/api/v1/admin/providers'),
	updateProviders: (payload: Record<string, unknown>) =>
		request<ProvidersSummary>('PUT', '/api/v1/admin/providers', payload),
	voskModels: () => request<VoskModelsResponse>('GET', '/api/v1/admin/vosk/models'),
	voskModelInstall: (name: string) =>
		request<{ queued: boolean; name: string }>('POST', `/api/v1/admin/vosk/models/${encodeURIComponent(name)}/install`),
	voskModelCancel: (name: string) =>
		request<unknown>('POST', `/api/v1/admin/vosk/models/${encodeURIComponent(name)}/cancel`),
	voskModelRemove: (name: string) =>
		request<{ removed: boolean; name: string; freed_bytes: number }>('DELETE', `/api/v1/admin/vosk/models/${encodeURIComponent(name)}`),
	testProvider: (target: SttProvider | 'analysis' | 'facilitator', apiKey?: string, baseUrl?: string, model?: string) =>
		request<{ ok: boolean; message: string }>('POST', '/api/v1/admin/providers/test', {
			target,
			api_key: apiKey,
			base_url: baseUrl,
			// the model typed into the form: the test used to ask the SAVED
			// one, so a retired model kept failing whatever was typed
			model,
		}),

	startRound: (roundId: string) => request<Round>('POST', `/api/v1/rounds/${roundId}/start`),
	endRound: (roundId: string) => request<Round>('POST', `/api/v1/rounds/${roundId}/end`),
	roundMonitor: (roundId: string) => request<RoundMonitor>('GET', `/api/v1/rounds/${roundId}/monitor`),
	/** The assembly's pre-registration link (made on first ask). */
	registrationLink: (assemblyId: string, create = true) =>
		request<RegistrationLink>(
			create ? 'POST' : 'GET',
			`/api/v1/assemblies/${assemblyId}/registration-link`,
		),
	/** The Live tab's "Pause AI" for one table ('default' follows the assembly). */
	setTableFacilitation: (assemblyId: string, tableNumber: number, level: 'default' | 'off' | 'light' | 'normal' | 'active') =>
		request<{ level: string; override: string | null }>(
			'POST', `/api/v1/assemblies/${assemblyId}/tables/${tableNumber}/facilitation`, { level },
		),
	/** What the AI facilitator said at each table of a session. */
	roundInterventions: (roundId: string) =>
		request<Intervention[]>('GET', `/api/v1/rounds/${roundId}/interventions`),
	acknowledgeHelp: (requestId: string) =>
		request<HelpRequest>('POST', `/api/v1/help-requests/${requestId}/acknowledge`),
	roundMessages: (roundId: string) =>
		request<SessionMessage[]>('GET', `/api/v1/rounds/${roundId}/messages`),
	sendMessage: (
		roundId: string,
		data: {
			kind: SessionMessage['kind']
			text?: string
			minutes?: number
			target_table_number?: number | null
			sound?: boolean
		},
	) => request<SessionMessage>('POST', `/api/v1/rounds/${roundId}/messages`, data),
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
	cancelAnalysis: (roundId: string) =>
		request<{ cancelled: number; running: number }>(
			'POST',
			`/api/v1/rounds/${roundId}/analysis/cancel`,
		),
	recluster: (roundId: string) =>
		request<{ queued: boolean }>('POST', `/api/v1/rounds/${roundId}/recluster`),
	assemblyReport: (assemblyId: string, includeDrafts: boolean) =>
		request<ReportData>(
			'GET',
			`/api/v1/assemblies/${assemblyId}/report?include_drafts=${includeDrafts}`,
		),
	/** Progress plus the newest FAILED synthesis/cross-table job, if any (R25).
	 * A separate endpoint from the report itself: lifecycle.assembly_progress()
	 * never carried failures, so the Report tab just looked unchanged forever
	 * when one of those jobs gave up. */
	assemblyProgress: (assemblyId: string) =>
		request<AssemblyProgress>('GET', `/api/v1/assemblies/${assemblyId}/progress`),
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
	/** Queue "How the discussion developed" across sessions (at least two with a summary). */
	generateSynthesis: (assemblyId: string) =>
		request<{ queued: boolean; sessions: number }>('POST', `/api/v1/assemblies/${assemblyId}/synthesis`),

	// ---- Polis seeds
	listSeeds: (assemblyId: string) =>
		request<SeedsListing>('GET', `/api/v1/assemblies/${assemblyId}/seeds`),
	generateSeeds: (assemblyId: string) =>
		request<{ queued: boolean }>('POST', `/api/v1/assemblies/${assemblyId}/seeds/generate`),
	createSeed: (assemblyId: string, text: string) =>
		request<StatementSeed>('POST', `/api/v1/assemblies/${assemblyId}/seeds`, { text }),
	updateSeed: (
		assemblyId: string,
		seedId: string,
		payload: { text?: string; status?: 'DRAFT' | 'APPROVED' | 'REJECTED' },
	) => request<StatementSeed>('PUT', `/api/v1/assemblies/${assemblyId}/seeds/${seedId}`, payload),
	reorderSeeds: (assemblyId: string, ids: string[]) =>
		request<{ seeds: StatementSeed[] }>('PUT', `/api/v1/assemblies/${assemblyId}/seeds/order`, { ids }),
	deleteSeed: (assemblyId: string, seedId: string) =>
		request<void>('DELETE', `/api/v1/assemblies/${assemblyId}/seeds/${seedId}`),

	listFiles: (assemblyId: string) =>
		request<FilesListing>('GET', `/api/v1/assemblies/${assemblyId}/files`),
	/** Each table phone's own log, read back after the fact (R17) — loaded on
	 * demand from the Files tab, never on its regular poll: it re-reads every
	 * phone's log file on the server and is only useful when something
	 * already looks wrong. */
	deviceReport: (assemblyId: string) =>
		request<DeviceReport>('GET', `/api/v1/assemblies/${assemblyId}/device-report`),
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
	/** Finish this recording now, with whatever audio has already arrived, and
	 * ask the phone to stop — the organizer's own version of the 5-minute
	 * silence sweep. 409 if the recording is not RECORDING any more. */
	finishRecording: (recordingId: string) =>
		request<{ state: string; finish_requested_at: string | null }>(
			'POST',
			`/api/v1/recordings/${recordingId}/finish`,
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
