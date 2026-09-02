<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import { mdiAlertCircleOutline, mdiCheckCircle, mdiQrcodeScan, mdiWifiOff } from '@mdi/js'
import { computed, onMounted, ref } from 'vue'
import SvgIcon from '../components/ui/SvgIcon.vue'
import { recorderApi, RecorderApiError, type JoinResult, type RoundInfo } from './api'
import { useI18n } from 'vue-i18n'
import { setLocale } from '../i18n'
import { decideOnStatusFailure } from './errors'
import { purgeLocalAudio, type PurgeOutcome } from './purge'
import ArmedScreen from './components/ArmedScreen.vue'
import ConsentScreen from './components/ConsentScreen.vue'
import Preflight from './components/Preflight.vue'
import RecordingScreen from './components/RecordingScreen.vue'
import RecoverySync from './components/RecoverySync.vue'
import ReportScreen from './components/ReportScreen.vue'
import { idb, type StoredRecording } from './idb'
import { initLogger } from './logger'

const SESSION_KEY = 'citizens-recorder-session'

type Screen =
	| 'joining'
	| 'no-invite'
	| 'offline'
	| 'purged'
	| 'recovery'
	| 'consent'
	| 'preflight'
	| 'armed'
	| 'recording'
	| 'report'
	| 'error'

const { t } = useI18n()

const screen = ref<Screen>('joining')
const error = ref('')
const session = ref<JoinResult | null>(null)
const selectedRound = ref<RoundInfo | null>(null)
const recoveryRecording = ref<StoredRecording | null>(null)

const joinBusy = ref(false)

const orchestrated = computed(() => session.value?.assembly.recording_mode === 'orchestrated')

/** Every table scans its QR within the same minute, so a burst at the door is
 * normal traffic, not abuse. A 429 here used to leave that table on a dead
 * error screen; retry with jittered backoff so phones don't collide again. */
async function joinWithRetry(token: string): Promise<JoinResult> {
	for (let attempt = 0; ; attempt++) {
		try {
			return await recorderApi.join(token)
		} catch (err) {
			const status = err instanceof RecorderApiError ? err.status : 0
			if ((status !== 429 && status < 500) || attempt >= 5) throw err
			joinBusy.value = true
			const backoff = 1500 * 2 ** attempt + Math.random() * 1500
			await new Promise((resolve) => setTimeout(resolve, backoff))
		}
	}
}

/** The round whose microphone just failed, if any.
 *
 * ArmedScreen auto-starts whatever round is ACTIVE. Without this latch a
 * microphone failure bounced the table straight back into the same round every
 * five seconds, forever.
 */
const micFailedRoundId = ref<string | null>(null)

/** What clearing this phone's copy actually did, once it has been asked for. */
const purgeOutcome = ref<PurgeOutcome | null>(null)

/** Act on the organizer's request to clear this phone.
 *
 * Only ever removes recordings the server has confirmed, and only this
 * assembly's — see purge.ts. Returns true when the citizen should be told,
 * which is whenever anything was actually deleted from their device.
 */
async function honourPurgeRequest(joined: JoinResult): Promise<boolean> {
	if (!joined.purge_local_audio) return false
	try {
		const outcome = await purgeLocalAudio(joined.assembly.id)
		if (outcome.cleared === 0) return false
		purgeOutcome.value = outcome
		screen.value = 'purged'
		return true
	} catch {
		return false // never let this stand between the table and recording
	}
}

function startRound(round: RoundInfo): void {
	// an explicit start (including "try again") clears the latch
	if (micFailedRoundId.value === round.id) micFailedRoundId.value = null
	selectedRound.value = round
	screen.value = 'recording'
}

/** Unsynchronized audio still on this phone, if any (brief §20).
 *
 * Deliberately independent of whether the server can be reached: audio waiting
 * on the device is exactly what matters when it cannot. This used to run only
 * on the way into a live session, so a failed status check left it unreachable
 * through the UI.
 */
async function scanForRecovery(assemblyId?: string): Promise<boolean> {
	try {
		const unfinished = await idb.unfinishedRecordings(assemblyId)
		const candidate = unfinished.find((r) => r.totalChunks !== null || r.startedAt > 0)
		if (!candidate) return false
		const chunks = await idb.chunksFor(candidate.recordingId)
		if (chunks.length > 0) {
			recoveryRecording.value = candidate
			screen.value = 'recovery'
			return true
		}
		await idb.deleteRecording(candidate.recordingId)
	} catch {
		/* recovery scan failure must not block a fresh session */
	}
	return false
}

async function enterWithSession(joined: JoinResult): Promise<void> {
	session.value = joined
	// The ROOM's language, not the phone's: this is a shared table device, and
	// everyone around it is discussing the assembly's question in one language.
	setLocale(joined.assembly.language)
	initLogger(joined.session_token)
	// the organizer has finished with this assembly and asked the phones to
	// drop their copies; it is this person's device, so say so
	if (await honourPurgeRequest(joined)) return
	// reload/crash recovery: unsynchronized local recordings take priority.
	// Scoped to THIS assembly — a citizen's own phone may still be carrying
	// audio from a previous event, and that must not stand between them and
	// recording this one.
	if (await scanForRecovery(joined.assembly.id)) return
	// people are about to be recorded: tell them what happens to the audio
	// before it starts. Once per device — an interrupted round must not make
	// the table read it again mid-assembly.
	if (!consentGiven()) {
		screen.value = 'consent'
		return
	}
	screen.value = 'preflight'
}

const CONSENT_KEY = 'citizens-recorder-consent'

function consentGiven(): boolean {
	try {
		return window.localStorage.getItem(CONSENT_KEY) === session.value?.assembly.id
	} catch {
		return false // private mode or blocked storage: show it again, never skip it
	}
}

function acceptConsent(): void {
	try {
		if (session.value) window.localStorage.setItem(CONSENT_KEY, session.value.assembly.id)
	} catch {
		/* not being able to remember is fine; showing it twice is not a failure */
	}
	screen.value = 'preflight'
}

onMounted(async () => {
	// 1) fresh QR join: #/join/<token>
	const match = window.location.hash.match(/#\/join\/(.+)$/)
	if (match) {
		try {
			const joined = await joinWithRetry(decodeURIComponent(match[1]))
			sessionStore(joined)
			// remove the invite secret from the visible URL (brief §14)
			history.replaceState(null, '', window.location.pathname + window.location.search)
			await enterWithSession(joined)
			return
		} catch (err) {
			error.value = err instanceof Error ? err.message : String(err)
			screen.value = 'error'
			return
		}
	}
	// 2) returning device with a stored session
	const stored = sessionLoad()
	if (stored) {
		if (await resumeStoredSession(stored)) return
	}
	// 3) no session at all, so nothing to scope by — offer whatever unsynced
	// audio is on this phone rather than leaving it unreachable
	if (await scanForRecovery()) return
	screen.value = 'no-invite'
})

/** Returns true when the boot is finished (resumed, or parked on 'offline'). */
async function resumeStoredSession(stored: JoinResult): Promise<boolean> {
	try {
		const status = await recorderApi.status(stored.session_token)
		await enterWithSession({ ...stored, ...status })
		return true
	} catch (err) {
		if (decideOnStatusFailure(err) === 'clear') {
			// the server has actually rejected this session: revoked invite,
			// deleted assembly. A new QR code is the only way forward.
			sessionStorageClear()
			return false
		}
		// Anything else — venue WiFi, a restarting container, a 500 — must NOT
		// cost the table its session. Keep it, show the audio that is still on
		// the phone if there is any, and offer a retry.
		session.value = stored
		initLogger(stored.session_token)
		if (await scanForRecovery(stored.assembly.id)) return true
		screen.value = 'offline'
		return true
	}
}

const retryBusy = ref(false)

async function retryStoredSession(): Promise<void> {
	const stored = sessionLoad()
	if (!stored) {
		screen.value = 'no-invite'
		return
	}
	retryBusy.value = true
	try {
		const status = await recorderApi.status(stored.session_token)
		await enterWithSession({ ...stored, ...status })
	} catch (err) {
		if (decideOnStatusFailure(err) === 'clear') {
			sessionStorageClear()
			screen.value = 'no-invite'
		}
		/* still unreachable: stay on the offline screen */
	} finally {
		retryBusy.value = false
	}
}

function sessionStore(joined: JoinResult): void {
	try {
		localStorage.setItem(SESSION_KEY, JSON.stringify(joined))
	} catch {
		/* private mode: session survives only until reload */
	}
}

function sessionLoad(): JoinResult | null {
	try {
		const raw = localStorage.getItem(SESSION_KEY)
		return raw ? (JSON.parse(raw) as JoinResult) : null
	} catch {
		return null
	}
}

function sessionStorageClear(): void {
	try {
		localStorage.removeItem(SESSION_KEY)
	} catch {
		/* ignore */
	}
}
</script>

<template>
	<div class="rc-screen">
		<div v-if="screen === 'joining'" class="rc-scroll">
			<div class="rc-hero" style="padding-top: 26vh">
				<div class="rc-hero__icon"><span class="rc-spin" style="width: 30px; height: 30px"></span></div>
				<p class="rc-muted">
					{{ joinBusy ? 'Lots of tables joining at once — waiting for a turn…' : 'Connecting to the assembly…' }}
				</p>
			</div>
		</div>

		<div v-else-if="screen === 'no-invite'" class="rc-scroll">
			<div class="rc-hero" style="padding-top: 18vh">
				<div class="rc-hero__icon"><SvgIcon :path="mdiQrcodeScan" :size="44" style="color: var(--rc-blue)" /></div>
				<h1>{{ t('recorder.noInvite.title') }}</h1>
				<p class="rc-muted" style="margin-top: 14px">
					{{ t('recorder.noInvite.body') }}<br />
					{{ t('recorder.noInvite.askFacilitator') }}
				</p>
			</div>
		</div>

		<div v-else-if="screen === 'purged'" class="rc-scroll">
			<div class="rc-hero" style="padding-top: 16vh">
				<div class="rc-hero__icon"><SvgIcon :path="mdiCheckCircle" :size="44" style="color: var(--rc-green)" /></div>
				<h1>{{ t('recorder.purged.title') }}</h1>
				<p class="rc-muted" style="margin-top: 14px">{{ t('recorder.purged.body') }}</p>
				<p v-if="purgeOutcome && purgeOutcome.keptUnsynced > 0" class="rc-alert" style="margin-top: 16px">
					{{ t('recorder.purged.kept', { count: purgeOutcome.keptUnsynced }, purgeOutcome.keptUnsynced) }}
				</p>
				<button class="rc-btn" style="margin-top: 22px" @click="screen = 'no-invite'">
					{{ t('recorder.purged.dismiss') }}
				</button>
			</div>
		</div>

		<div v-else-if="screen === 'offline'" class="rc-scroll">
			<div class="rc-hero" style="padding-top: 16vh">
				<div class="rc-hero__icon">
					<SvgIcon :path="mdiWifiOff" :size="44" style="color: var(--rc-amber)" />
				</div>
				<h1>{{ t('recorder.offline.title') }}</h1>
				<p class="rc-muted" style="margin-top: 14px">{{ t('recorder.offline.body') }}</p>
				<button class="rc-btn" :disabled="retryBusy" style="margin-top: 22px" @click="retryStoredSession">
					{{ retryBusy ? t('recorder.offline.retrying') : t('recorder.offline.retry') }}
				</button>
			</div>
		</div>

		<div v-else-if="screen === 'error'" class="rc-scroll">
			<div class="rc-hero" style="padding-top: 14vh">
				<div class="rc-hero__icon"><SvgIcon :path="mdiAlertCircleOutline" :size="44" style="color: var(--rc-red)" /></div>
				<h1>{{ t('recorder.joinError.title') }}</h1>
				<div class="rc-alert" style="text-align: left">{{ error }}</div>
				<p class="rc-muted">{{ t('recorder.joinError.hint') }}</p>
			</div>
		</div>

		<RecoverySync
			v-else-if="screen === 'recovery' && session && recoveryRecording"
			:session="session"
			:recording="recoveryRecording"
			@done="recoveryRecording = null; screen = 'preflight'" />

		<ConsentScreen
			v-else-if="screen === 'consent' && session"
			:handling="session.data_handling ?? null"
			:table-number="session.table_number"
			@accept="acceptConsent" />

		<Preflight
			v-else-if="screen === 'preflight' && session"
			:session="session"
			@ready="screen = 'armed'"
			@start="startRound"
			@report="screen = 'report'" />

		<ArmedScreen
			v-else-if="screen === 'armed' && session"
			:session="session"
			:blocked-round-id="micFailedRoundId"
			@start="startRound"
			@back="screen = 'preflight'"
			@report="screen = 'report'" />

		<ReportScreen
			v-else-if="screen === 'report' && session"
			:session="session"
			@back="screen = orchestrated ? 'armed' : 'preflight'" />

		<RecordingScreen
			v-else-if="screen === 'recording' && session && selectedRound"
			:key="selectedRound.id"
			:session="session"
			:round="selectedRound"
			@exit="screen = orchestrated ? 'armed' : 'preflight'"
			@next-round="startRound"
			@mic-failed="micFailedRoundId = $event"
			@view-report="screen = 'report'" />
	</div>
</template>
