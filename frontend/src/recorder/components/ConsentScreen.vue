<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
/**
 * The notice, and the people who registered against it (0.7).
 *
 * People at the table are about to have their voices recorded. The server
 * renders what happens to that audio — who is responsible, which engine
 * hears it and whether it is somebody else's service, how long the recording
 * is kept, their rights, the legal basis — in the assembly's language and
 * hashed exactly as shown. Each person then registers one at a time on this
 * phone (ConsentForm), or scans the table's registration code and does it on
 * their own (RegisterPage): both land on the same roster here. A refusal is
 * recorded too. The record is individual; nothing here is one tick for the
 * table.
 *
 * 'required' assemblies continue only once one person here has consented
 * (the server enforces the same rule where recording starts); 'optional'
 * ones continue at once. A server older than 0.7 has no notice endpoint:
 * the screen then falls back to the table-level text it always showed.
 */
import { computed, type ComponentPublicInstance, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { setLocale } from '../../i18n'
import {
	recorderApi,
	RecorderApiError,
	type AssemblyInfo,
	type ConsentNotice,
	type DataHandling,
	type Joined,
	type RecorderLanguage,
	type TableConsent,
	type UnseatedParticipant,
} from '../api'
import { slotLabel } from '../slots'
import CapabilityQr from './CapabilityQr.vue'
import ConsentForm, { type ConsentFormValue } from './ConsentForm.vue'
import TableBadge from './TableBadge.vue'

const props = defineProps<{
	token: string
	handling: DataHandling | null
	tableNumber: number
	colorKey?: string | null
	/** needed for the language switch (kind === 'session' && language_changeable) */
	assembly?: AssemblyInfo | null
	/** what the code this phone just scanned made it, shown once as a line
	 * above the notice (0.8: folded in from the old JoinedScreen) */
	pendingJoined?: Joined | null
	/** this device already consented for this assembly — the heavy notice is
	 * skipped; only the joined line (if any) and a way through are shown */
	alreadyConsented?: boolean
}>()
const emit = defineEmits<{ accept: [table: TableConsent | null]; deny: [] }>()

const { t } = useI18n()

const joinedLine = computed(() => {
	const joined = props.pendingJoined
	if (!joined) return ''
	return joined.table_created
		? t('recorder.joined.newTable')
		: t('recorder.joined.asRecorder', { label: slotLabel(joined.slot) })
})

const notice = ref<ConsentNotice | null>(null)
const legacy = ref(false)
const loading = ref(true)
const view = ref<'notice' | 'form' | 'added'>('notice')
const busy = ref(false)
const failed = ref('')
const added = ref<{ name: string; consented: boolean } | null>(null)
const table = ref<TableConsent | null>(null)
const ownPhone = ref(false)
let roster = 0

/* ---- "Already registered? Find your name" ----
 * People who registered ahead through the assembly's link have no table yet;
 * the door seats them here by name. Two characters, names only. */
const finding = ref(false)
const query = ref('')
const matches = ref<UnseatedParticipant[]>([])
const seating = ref('')
let searchTimer = 0

function search(): void {
	window.clearTimeout(searchTimer)
	const q = query.value.trim()
	if (q.length < 2) {
		matches.value = []
		return
	}
	searchTimer = window.setTimeout(async () => {
		try {
			matches.value = await recorderApi.searchParticipants(props.token, q)
		} catch {
			matches.value = []
		}
	}, 250)
}

async function seat(person: UnseatedParticipant): Promise<void> {
	if (seating.value) return
	seating.value = person.id
	try {
		const result = await recorderApi.seatParticipant(props.token, person.id)
		table.value = result.table
		matches.value = matches.value.filter((m) => m.id !== person.id)
		query.value = ''
		finding.value = false
		await load()
	} catch {
		/* the next tap will say */
	} finally {
		seating.value = ''
	}
}

/** Somebody at the table objects (legacy screen only). Consent that offers
 * only one button is not consent. */
const declined = ref(false)

async function load(): Promise<void> {
	try {
		notice.value = await recorderApi.consentNotice(props.token)
		legacy.value = false
	} catch {
		if (!notice.value) legacy.value = true // a server older than 0.7, or a blink: the old text
	} finally {
		loading.value = false
	}
}
onMounted(() => {
	// the minimal card (already consented) never shows the notice, so there is
	// nothing here worth fetching
	if (props.alreadyConsented) return
	void load()
	// people registering on their own phones appear here as they do
	roster = window.setInterval(() => {
		if (view.value === 'notice') void load()
	}, 10_000)
})
onBeforeUnmount(() => {
	window.clearInterval(roster)
	frameObserver?.disconnect()
})

/* ---- scroll-gated Accept: the notice must be read to its end, not just
 * glanced at, before the one acceptance box can be ticked away by a tap ---- */
const frameEl = ref<HTMLElement | null>(null)
const readToEnd = ref(false)
let frameObserver: ResizeObserver | undefined

function checkReadToEnd(): void {
	const el = frameEl.value
	if (!el) return
	readToEnd.value = el.scrollTop + el.clientHeight >= el.scrollHeight - 8
}

/** A function ref, not a plain one: the frame mounts fresh every time this
 * view is re-entered (returning from the registration form, say), and only a
 * mount callback — not a watcher on `notice` — fires every one of those
 * times, including the very first. Typed loosely to match Vue's own function
 * ref signature; this is always a plain <div>, never a component. */
function attachFrame(el: Element | ComponentPublicInstance | null): void {
	frameObserver?.disconnect()
	frameObserver = undefined
	frameEl.value = el as HTMLElement | null
	if (!frameEl.value) return
	checkReadToEnd()
	// a notice short enough to fit needs no scrolling at all; a resize (the
	// keyboard opening, a rotate) can turn a scrollable notice into one that
	// already fits, or back — recheck either way. Absent in some test
	// environments, so this stays optional.
	if (typeof ResizeObserver === 'undefined') return
	frameObserver = new ResizeObserver(checkReadToEnd)
	frameObserver.observe(frameEl.value)
}

/* ---- the language switch: a Record-now Session only, before any recording
 * exists (assembly.language_changeable) ---- */
const LANGUAGE_FLAGS: Record<RecorderLanguage, string> = {
	en: '🇬🇧', it: '🇮🇹', de: '🇩🇪', fr: '🇫🇷', es: '🇪🇸',
}
const LANGUAGE_CODES = Object.keys(LANGUAGE_FLAGS) as RecorderLanguage[]

const showLanguage = computed(
	() => props.assembly?.kind === 'session' && props.assembly?.language_changeable === true,
)
const selectedLanguage = ref<RecorderLanguage>((props.assembly?.language as RecorderLanguage) ?? 'en')
const languageBusy = ref(false)

async function changeLanguage(code: string): Promise<void> {
	const language = code as RecorderLanguage
	const previous = selectedLanguage.value
	if (language === previous || languageBusy.value) return
	selectedLanguage.value = language
	languageBusy.value = true
	failed.value = ''
	try {
		await recorderApi.changeLanguage(props.token, language)
		setLocale(language)
		readToEnd.value = false // new text in a new language: read it again
		await load() // the notice itself is rendered server-side, in that language
		// the frame's DOM node survives this (notice is reassigned, not toggled
		// away), so nothing remounts it — recheck once the new text has rendered
		await nextTick()
		checkReadToEnd()
	} catch (err) {
		selectedLanguage.value = previous // the table stays in the language everyone was told about
		failed.value =
			err instanceof RecorderApiError ? err.message : err instanceof Error ? err.message : String(err)
	} finally {
		languageBusy.value = false
	}
}

const consenting = computed(
	() => notice.value?.participants.filter((p) => p.recording_consent).length ?? 0,
)
/** seated people whose newest act refuses or withdraws: one blocks a
 * required table until marked as moved, or until they change their mind */
const refusing = computed(() => notice.value?.participants.filter((p) => p.refused).length ?? 0)
const required = computed(() => notice.value?.mode === 'required')
const canContinue = computed(
	() => legacy.value || !required.value || (consenting.value > 0 && refusing.value === 0),
)

/* ---- the roster's actions: changed their mind, withdraws, moved ---- */
const changing = ref<{ id: string; name: string } | null>(null)
const withdrawing = ref<{ id: string; name: string } | null>(null)
const acting = ref('')

function startForm(): void {
	failed.value = ''
	changing.value = null
	view.value = 'form'
}

function startChange(person: { id: string; name: string }): void {
	failed.value = ''
	changing.value = person
	view.value = 'form'
}

/** A refusal reversed on the same phone: a further act, their name fixed. */
async function confirmChange(value: ConsentFormValue): Promise<void> {
	if (!notice.value || !changing.value || busy.value) return
	busy.value = true
	failed.value = ''
	try {
		const result = await recorderApi.changeConsent(props.token, changing.value.id, {
			notice_hash: notice.value.hash,
			notice_read: true,
			recording_consent: value.accepted,
			transcription_consent: value.accepted,
			analysis_consent: value.accepted,
			publication_consent: value.accepted && value.quotations,
		})
		table.value = result.table
		changing.value = null
		await load()
		view.value = 'notice'
	} catch (err) {
		const message = err instanceof Error ? err.message : String(err)
		const stale = /NOTICE_CHANGED|notice has changed/i.test(message)
		failed.value = stale ? t('recorder.consent.form.stale') : t('recorder.consent.form.failed')
		if (stale) await load()
	} finally {
		busy.value = false
	}
}

/** Withdraws consent: every flag false; the recording so far is kept. */
async function withdraw(): Promise<void> {
	if (!notice.value || !withdrawing.value || acting.value) return
	acting.value = withdrawing.value.id
	try {
		const result = await recorderApi.changeConsent(props.token, withdrawing.value.id, {
			notice_hash: notice.value.hash,
			notice_read: true,
			recording_consent: false,
			transcription_consent: false,
			analysis_consent: false,
			publication_consent: false,
		})
		table.value = result.table
		withdrawing.value = null
		await load()
	} catch {
		failed.value = t('recorder.consent.form.failed')
	} finally {
		acting.value = ''
	}
}

/** Moved to another table — one that is not recorded. */
async function moved(person: { id: string }): Promise<void> {
	if (acting.value) return
	acting.value = person.id
	try {
		const result = await recorderApi.markMoved(props.token, person.id)
		table.value = result.table
		await load()
	} catch {
		failed.value = t('recorder.consent.form.failed')
	} finally {
		acting.value = ''
	}
}

async function submit(value: ConsentFormValue, refuse: boolean): Promise<void> {
	if (!notice.value || busy.value) return
	busy.value = true
	failed.value = ''
	try {
		// the required box covers recording, transcription and analysis; the
		// quotations box is its own answer; a refusal clears them all
		const yes = !refuse && value.accepted
		const result = await recorderApi.registerParticipant(props.token, {
			name: value.name,
			email: value.email,
			notice_hash: notice.value.hash,
			notice_read: true,
			recording_consent: yes,
			transcription_consent: yes,
			analysis_consent: yes,
			publication_consent: yes && value.quotations,
		})
		table.value = result.table
		added.value = { name: result.participant.name, consented: result.can_record }
		// the roster, without a second round-trip
		notice.value = {
			...notice.value,
			participants: [
				...notice.value.participants,
				{
					id: result.participant.id,
					label: result.participant.label,
					name: result.participant.name,
					recording_consent: result.can_record,
					publication_consent: yes && value.quotations,
					refused: !result.can_record,
				},
			],
		}
		view.value = 'added'
	} catch (err) {
		const message = err instanceof Error ? err.message : String(err)
		const stale = /NOTICE_CHANGED|notice has changed/i.test(message)
		failed.value = stale ? t('recorder.consent.form.stale') : t('recorder.consent.form.failed')
		if (stale) await load()
	} finally {
		busy.value = false
	}
}

function accept(): void {
	emit('accept', table.value)
}

/* ---- the table-level text, for a server without the notice endpoint ---- */
const ENGINE_NAMES: Record<string, string> = {
	deepgram: 'Deepgram',
	mistral: 'Mistral',
	whisper: 'Whisper',
	vosk: 'Vosk',
}
const engine = computed(
	() => ENGINE_NAMES[props.handling?.stt_provider ?? ''] ?? t('recorder.consent.engineFallback'),
)
const audioDestination = computed(() => {
	if (!props.handling) return t('recorder.consent.notConfigured')
	if (!props.handling.stt_configured) return t('recorder.consent.noEngine')
	return props.handling.stt_hosted
		? t('recorder.consent.audioHosted', { engine: engine.value })
		: t('recorder.consent.audioSelfHosted', { engine: engine.value })
})
const transcriptDestination = computed(() => {
	if (!props.handling?.analysis_enabled) return null
	return props.handling.analysis_hosted
		? t('recorder.consent.transcriptHosted')
		: t('recorder.consent.transcriptSelfHosted')
})
const retention = computed(() => {
	const days = props.handling?.audio_retention_days ?? 0
	if (days > 0) return t('recorder.consent.retentionDays', { days }, days)
	return t('recorder.consent.retentionForever')
})
</script>

<template>
	<!-- this device already consented for this assembly: skip the heavy
	     notice, relay only what the scanned code decided -->
	<div v-if="alreadyConsented" class="rc-scroll">
		<div class="rc-hero" style="padding-top: 16vh">
			<TableBadge :number="tableNumber" :color-key="colorKey" hero />
			<h1 v-if="pendingJoined" style="margin-top: 18px" data-test="joined-line">{{ joinedLine }}</h1>
			<button class="rc-btn rc-primary" style="margin-top: 22px" data-test="continue" @click="accept">
				{{ t('recorder.joined.continue') }}
			</button>
		</div>
	</div>

	<!-- one person registering -->
	<div v-else-if="view === 'form' && notice && changing" class="rc-scroll rc-pad">
		<h1>{{ t('recorder.consent.form.changedMindTitle', { name: changing.name }) }}</h1>
		<p class="rc-muted" style="margin: 6px 0 0">{{ t('recorder.consent.form.changedMindLead') }}</p>
		<ConsentForm
			:busy="busy"
			:failed="failed"
			:acceptance="notice.acceptance"
			:acceptance-quotations="notice.acceptance_quotations"
			:fixed-name="changing.name"
			@confirm="confirmChange"
			@cancel="view = 'notice'" />
	</div>
	<div v-else-if="view === 'form' && notice" class="rc-scroll rc-pad">
		<h1>{{ t('recorder.consent.form.title') }}</h1>
		<p class="rc-muted" style="margin: 6px 0 0">{{ t('recorder.consent.form.lead') }}</p>
		<ConsentForm
			:busy="busy"
			:failed="failed"
			:acceptance="notice.acceptance"
			:acceptance-quotations="notice.acceptance_quotations"
			@confirm="(value) => submit(value, false)"
			@refuse="(value) => submit(value, true)"
			@cancel="view = 'notice'" />
	</div>

	<!-- one person done -->
	<div v-else-if="view === 'added' && added" class="rc-scroll rc-pad rc-center">
		<h1 style="margin-top: 10vh">
			{{ added.consented ? t('recorder.consent.added.title') : t('recorder.consent.added.refused') }}
		</h1>
		<p class="rc-lead">{{ added.name }}</p>
		<p v-if="!added.consented" class="rc-muted">{{ t('recorder.consent.added.refusedBody') }}</p>
		<button class="rc-btn" style="margin-top: 22px" @click="startForm">
			{{ t('recorder.consent.added.another') }}
		</button>
		<button class="rc-btn rc-primary" :disabled="!canContinue" data-test="continue" @click="accept">
			{{ t('recorder.consent.continue') }}
		</button>
		<p v-if="!canContinue" class="rc-muted rc-consent__hint">
			{{ refusing > 0 ? t('recorder.consent.requiredHintRefused') : t('recorder.consent.requiredHint') }}
		</p>
	</div>

	<!-- the legacy table-level screen: somebody objected -->
	<div v-else-if="legacy && declined" class="rc-scroll rc-pad">
		<h1>{{ t('recorder.consent.declinedTitle') }}</h1>
		<p class="rc-lead">{{ t('recorder.consent.declinedBody') }}</p>
		<button class="rc-btn" @click="declined = false">
			{{ t('recorder.consent.declinedBack') }}
		</button>
	</div>

	<!-- the notice: a fixed column (header, a scroll-gated frame, a pinned
	     footer) so Accept cannot be reached without scrolling to the end -->
	<div v-else class="rc-fill">
		<div class="rc-consent__head">
			<TableBadge :number="tableNumber" :color-key="colorKey" />
			<div v-if="showLanguage" class="rc-lang">
				<span class="rc-lang__flag" aria-hidden="true">{{ LANGUAGE_FLAGS[selectedLanguage] }}</span>
				<select
					data-test="language"
					:aria-label="t('recorder.consent.language')"
					:value="selectedLanguage"
					:disabled="languageBusy"
					@change="changeLanguage(($event.target as HTMLSelectElement).value)">
					<option v-for="code in LANGUAGE_CODES" :key="code" :value="code">{{ code.toUpperCase() }}</option>
				</select>
			</div>
		</div>
		<p v-if="pendingJoined" class="rc-eyebrow" data-test="joined-line">{{ joinedLine }}</p>
		<h1>{{ t('recorder.consent.title', { number: tableNumber }) }}</h1>
		<p class="rc-lead">{{ t('recorder.consent.lead') }}</p>

		<p v-if="loading" class="rc-muted">…</p>
		<template v-else-if="notice">
			<div :ref="attachFrame" class="rc-notice-frame" data-test="notice-frame" @scroll="checkReadToEnd">
				<div class="rc-notice" data-test="notice">
					<p v-for="(paragraph, index) in notice.paragraphs" :key="index">{{ paragraph }}</p>
				</div>

				<h2 class="rc-consent__roster-title">{{ t('recorder.consent.registeredTitle') }}</h2>
				<ul v-if="notice.participants.length" class="rc-roster" data-test="roster">
					<li v-for="person in notice.participants" :key="person.label">
						<span>{{ person.name }}</span>
						<span :class="person.recording_consent ? 'rc-roster__yes' : 'rc-roster__no'">
							{{ person.recording_consent ? t('recorder.consent.consented') : t('recorder.consent.refusedNote') }}
							<template v-if="person.recording_consent && person.publication_consent === false">
								· {{ t('recorder.consent.quotationsNo') }}
							</template>
						</span>
						<!-- the newest act counts: a refusal can be reversed here, a
						     refuser marked as moved, a consent withdrawn -->
						<span v-if="person.id && person.refused" class="rc-roster__actions">
							<button type="button" class="rc-btn rc-subtle" :disabled="!!acting" data-test="changed-mind" @click="startChange({ id: person.id, name: person.name })">
								{{ t('recorder.consent.changedMind') }}
							</button>
							<button type="button" class="rc-btn rc-subtle" :disabled="!!acting" data-test="moved" @click="moved({ id: person.id })">
								{{ t('recorder.consent.moved') }}
							</button>
						</span>
						<span v-else-if="person.id && person.recording_consent" class="rc-roster__actions">
							<button type="button" class="rc-btn rc-subtle" :disabled="!!acting" data-test="withdraw" @click="withdrawing = { id: person.id, name: person.name }">
								{{ t('recorder.consent.withdraw') }}
							</button>
						</span>
					</li>
				</ul>
				<p v-else class="rc-muted" style="margin: 0">{{ t('recorder.consent.none') }}</p>
				<p v-if="refusing > 0" class="rc-alert" role="alert" data-test="refused-hint">
					{{ t('recorder.consent.requiredHintRefused') }}
				</p>
				<div v-if="withdrawing" class="rc-card" role="dialog" style="text-align: left" data-test="withdraw-confirm">
					<p>{{ t('recorder.consent.withdrawConfirm', { name: withdrawing.name }) }}</p>
					<button type="button" class="rc-btn rc-primary" :disabled="!!acting" data-test="withdraw-yes" @click="withdraw">
						{{ t('recorder.consent.withdrawYes') }}
					</button>
					<button type="button" class="rc-btn rc-subtle" :disabled="!!acting" @click="withdrawing = null">
						{{ t('recorder.consent.form.cancel') }}
					</button>
				</div>
				<p v-if="failed && view === 'notice'" class="rc-alert">{{ failed }}</p>

				<button class="rc-btn" style="margin-top: 16px" data-test="add" @click="startForm">
					{{ t('recorder.consent.add') }}
				</button>
				<button class="rc-btn rc-subtle" data-test="own-phone" @click="ownPhone = true">
					{{ t('recorder.consent.ownPhone') }}
				</button>
				<!-- registered ahead through the assembly's link: seated here by name -->
				<button v-if="!finding" class="rc-btn rc-subtle" data-test="find" @click="finding = true">
					{{ t('recorder.consent.findName') }}
				</button>
				<div v-else class="rc-find" data-test="finder">
					<input
						v-model="query"
						type="search"
						class="rc-find__input"
						autocomplete="off"
						:placeholder="t('recorder.consent.findPlaceholder')"
						data-test="find-input"
						@input="search" />
					<ul v-if="matches.length" class="rc-roster" data-test="matches">
						<li v-for="person in matches" :key="person.id">
							<span>{{ person.name }}</span>
							<button type="button" class="rc-find__seat" :disabled="!!seating" :data-test="`seat-${person.id}`" @click="seat(person)">
								{{ t('recorder.consent.seatHere') }}
							</button>
						</li>
					</ul>
					<p v-else-if="query.trim().length >= 2" class="rc-muted" style="font-size: 0.875rem; margin: 6px 0 0">
						{{ t('recorder.consent.nobodyFound') }}
					</p>
				</div>
			</div>

			<div class="rc-consent__footer">
				<p v-if="!readToEnd" class="rc-muted rc-consent__hint" data-test="scroll-hint">{{ t('recorder.consent.scrollToEnd') }}</p>
				<div class="rc-consent__actions">
					<button
						class="rc-btn"
						:class="{ 'rc-primary': readToEnd }"
						:disabled="!readToEnd || !canContinue"
						data-test="continue"
						@click="accept">
						{{ t('recorder.consent.continue') }}
					</button>
					<button class="rc-btn rc-subtle" data-test="deny" @click="emit('deny')">
						{{ t('recorder.consent.deny') }}
					</button>
				</div>
				<p v-if="!canContinue" class="rc-muted rc-consent__hint">{{ t('recorder.consent.requiredHint') }}</p>
			</div>
		</template>

		<!-- a server without the notice endpoint: the table-level text, free
		     to scroll on its own — this device predates the scroll gate -->
		<div v-else class="rc-scroll">
			<ul class="rc-consent">
				<li>{{ t('recorder.consent.records') }}</li>
				<li>{{ audioDestination }}</li>
				<li v-if="transcriptDestination">{{ transcriptDestination }}</li>
				<li>{{ retention }}</li>
				<li>{{ t('recorder.consent.speakers') }}</li>
				<li>{{ t('recorder.consent.reviewed') }}</li>
			</ul>
			<p class="rc-muted rc-consent__ask">{{ t('recorder.consent.ask') }}</p>
			<button class="rc-btn rc-primary" data-test="continue" @click="accept">
				{{ t('recorder.consent.agree') }}
			</button>
			<button class="rc-btn rc-subtle" @click="declined = true">
				{{ t('recorder.consent.decline') }}
			</button>
		</div>
	</div>

	<!-- the table's registration code, for people's own phones -->
	<div v-if="ownPhone" class="rc-sheet-scrim" @click.self="ownPhone = false">
		<div class="rc-sheet" role="dialog" aria-modal="true">
			<CapabilityQr
				:token="token"
				purpose="REGISTER_PARTICIPANT"
				:table-number="tableNumber"
				:color-key="colorKey"
				@close="ownPhone = false" />
		</div>
	</div>
</template>

<style scoped>
.rc-pad {
	padding: 6px 2px calc(12px + env(safe-area-inset-bottom, 0px));
}
.rc-lead {
	font-size: 1.02rem;
	line-height: 1.5;
	margin: 8px 0 0;
}
/* the notice view: a fixed column, not a page that scrolls — only the frame
   below does. Scoped, so this leaves every other screen's .rc-fill alone. */
.rc-fill { padding: 6px 2px calc(12px + env(safe-area-inset-bottom, 0px)); }
.rc-notice-frame {
	flex: 1 1 auto;
	min-height: 0;
	overflow-y: auto;
	-webkit-overflow-scrolling: touch;
}
.rc-consent__footer { flex-shrink: 0; padding-top: 10px; }
.rc-consent__actions { display: flex; gap: 10px; flex-wrap: wrap; }
.rc-consent__actions .rc-btn { width: auto; flex: 0 1 auto; margin-top: 0; padding: 10px 20px; }
.rc-consent__head {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 10px;
	margin: 4px 0 10px;
}
.rc-lang {
	display: inline-flex;
	align-items: center;
	gap: 4px;
	border: 1px solid var(--rc-border);
	border-radius: 999px;
	padding: 4px 10px 4px 12px;
	font-size: 0.8125rem;
	background: var(--rc-surface);
	flex-shrink: 0;
}
.rc-lang__flag { font-size: 1rem; line-height: 1; }
.rc-lang select {
	border: none;
	background: transparent;
	font: inherit;
	font-weight: 700;
	color: inherit;
	cursor: pointer;
	padding: 0;
}
.rc-lang select:focus { outline: none; }
.rc-consent__roster-title {
	font-size: 0.75rem;
	letter-spacing: 0.1em;
	text-transform: uppercase;
	color: var(--rc-muted);
	margin: 18px 0 6px;
}
.rc-roster {
	list-style: none;
	margin: 0;
	padding: 0;
}
.rc-roster li {
	display: flex;
	justify-content: space-between;
	gap: 10px;
	padding: 8px 0;
	border-bottom: 1px solid var(--rc-border);
}
.rc-roster__yes { color: #1e6b3a; font-weight: 600; }
.rc-roster__no { color: #8c1d18; font-weight: 600; }
.rc-roster__actions { display: flex; gap: 6px; flex-wrap: wrap; width: 100%; margin-top: 6px; }
.rc-roster__actions .rc-btn { margin: 0; padding: 8px 10px; font-size: 0.8125rem; min-height: 36px; }
.rc-consent__hint { margin: 8px 0 0; font-size: 0.875rem; }
.rc-find { margin: 6px 0 0; }
.rc-find__input {
	width: 100%;
	box-sizing: border-box;
	font: inherit;
	font-size: 1.0625rem;
	padding: 12px 14px;
	border: 1px solid var(--rc-border);
	border-radius: 12px;
	background: var(--rc-surface);
	color: inherit;
}
.rc-find__seat {
	background: var(--rc-blue);
	border: 0;
	border-radius: 999px;
	color: #fff;
	font: inherit;
	font-size: 0.8125rem;
	min-height: 36px;
	padding: 4px 14px;
	cursor: pointer;
}
.rc-consent {
	margin: 18px 0 0;
	padding-left: 20px;
	line-height: 1.55;
}
.rc-consent li + li { margin-top: 10px; }
.rc-consent__ask { margin: 20px 0 18px; }
</style>
