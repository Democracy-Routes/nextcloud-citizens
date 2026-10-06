<!--
	SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
	SPDX-License-Identifier: AGPL-3.0-or-later

	The facilitator's own phone beside ONE table (0.7). Scanned from the
	table phone's "Add facilitator" code, it follows the session — question,
	goal, time left — and the table: who registered and consented, the hand,
	the organizer's messages, the AI facilitator's advice when it is on. From
	here the facilitator writes a prompt to the table's phones, raises the
	table's hand, registers for consent, or hands this phone over to the
	recorder app as a second recorder. It never records.

	Polls the status every few seconds and ticks the clock locally between
	polls; a heartbeat every half minute tells the server this phone is still
	here, so advice comes here rather than to the table.
-->
<script setup lang="ts">
import { mdiHandBackLeft } from '@mdi/js'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import SvgIcon from '../../components/ui/SvgIcon.vue'
import { setLocale } from '../../i18n'
import { recorderApi, type FacilitatorStatus, type HelpKind, type PhoneMessage } from '../api'
import TableBadge from './TableBadge.vue'

const props = defineProps<{
	token: string
	/** a participant registration already made on this phone */
	registered?: boolean
}>()
const emit = defineEmits<{
	forget: []
	/** open the table's registration code on this phone (the person registers themselves) */
	register: [token: string]
	/** this phone becomes a recorder of the table: the recorder app takes over */
	becomeRecorder: [url: string]
}>()

const { t } = useI18n()

const status = ref<FacilitatorStatus | null>(null)
const gone = ref(false)
const now = ref(Date.now())
/** when the status was read, so the clock can run between polls */
let readAt = Date.now()
let poll = 0
let ticker = 0
let heartbeat = 0

const POLL_MS = 5_000
const HEARTBEAT_MS = 30_000

/* ---- the clock ---- */
const secondsLeft = computed(() => {
	const round = status.value?.round
	if (!round || round.seconds_left === null) return null
	return round.seconds_left - Math.round((now.value - readAt) / 1000)
})
const clockText = computed(() => {
	const left = secondsLeft.value
	if (left === null) return ''
	if (left <= -60) return t('recorder.facilitator.overBy', { minutes: Math.floor(-left / 60) })
	if (left < 60) return t('recorder.facilitator.lastMinute')
	return t('recorder.facilitator.timeLeft', { minutes: Math.ceil(left / 60) })
})
const clockClass = computed(() => {
	const left = secondsLeft.value
	if (left === null) return ''
	if (left <= 0) return 'rc-fac-clock--over'
	if (left < 60) return 'rc-fac-clock--last'
	return ''
})

/* ---- messages from the organizer: shown until dismissed, receipt posted ---- */
const messages = ref<PhoneMessage[]>([])
let newestSeen = 0
function ingest(fresh: PhoneMessage[]): void {
	for (const message of fresh) {
		if (message.id <= newestSeen) continue
		newestSeen = message.id
		messages.value = [...messages.value, message].slice(-5)
		void recorderApi.facilitatorMessageSeen(props.token, message.id).catch(() => undefined)
	}
}
function dismissMessage(id: number): void {
	messages.value = messages.value.filter((m) => m.id !== id)
}

/* ---- a prompt to the table ---- */
const prompt = ref('')
const sending = ref(false)
const sentAt = ref<number | null>(null)
const promptFailed = ref(false)
async function send(): Promise<void> {
	const text = prompt.value.trim()
	if (!text || sending.value) return
	sending.value = true
	promptFailed.value = false
	try {
		await recorderApi.facilitatorPrompt(props.token, text)
		prompt.value = ''
		sentAt.value = Date.now()
		window.setTimeout(() => (sentAt.value = null), 4000)
	} catch {
		promptFailed.value = true
	} finally {
		sending.value = false
	}
}

/* ---- the table's hand ---- */
const helpOpen = ref(false)
const helpBusy = ref(false)
const KINDS: HelpKind[] = ['TECHNICAL', 'ORGANIZER', 'PROCESS']
async function askHelp(kind: HelpKind): Promise<void> {
	helpBusy.value = true
	try {
		const state = await recorderApi.facilitatorHelp(props.token, kind)
		if (status.value) status.value = { ...status.value, help: state }
		helpOpen.value = false
	} catch {
		/* the next poll says */
	} finally {
		helpBusy.value = false
	}
}

/* ---- this phone: register, or record ---- */
const registering = ref(false)
async function register(): Promise<void> {
	registering.value = true
	try {
		const card = await recorderApi.facilitatorCode(props.token, 'REGISTER_PARTICIPANT')
		const match = card.url.match(/#\/register\/(.+)$/)
		if (match) emit('register', decodeURIComponent(match[1]))
	} catch {
		/* a reload and another tap */
	} finally {
		registering.value = false
	}
}
const recorderConfirm = ref(false)
const recorderBusy = ref(false)
async function becomeRecorder(): Promise<void> {
	recorderBusy.value = true
	try {
		const card = await recorderApi.facilitatorCode(props.token, 'ADD_RECORDER_TO_TABLE')
		recorderConfirm.value = false
		emit('becomeRecorder', card.url)
	} catch {
		/* stay here */
	} finally {
		recorderBusy.value = false
	}
}

/* ---- the AI facilitator's advice: the facilitator decides ---- */
const adviceBusy = ref<string | null>(null)
const sentAdvice = ref<Set<string>>(new Set())
const ratedAdvice = ref<Record<string, boolean>>({})
async function dismissAdvice(id: string): Promise<void> {
	adviceBusy.value = id
	try {
		await recorderApi.facilitatorAdviceDismiss(props.token, id)
		if (status.value) status.value = { ...status.value, advice: status.value.advice.filter((a) => a.id !== id) }
	} catch {
		/* the next poll says */
	} finally {
		adviceBusy.value = null
	}
}
async function sendAdvice(id: string): Promise<void> {
	adviceBusy.value = id
	try {
		await recorderApi.facilitatorAdviceSend(props.token, id)
		sentAdvice.value = new Set([...sentAdvice.value, id])
		window.setTimeout(() => {
			if (status.value) status.value = { ...status.value, advice: status.value.advice.filter((a) => a.id !== id) }
		}, 2500)
	} catch {
		/* the next poll says */
	} finally {
		adviceBusy.value = null
	}
}
function rateAdvice(id: string, helpful: boolean): void {
	ratedAdvice.value = { ...ratedAdvice.value, [id]: helpful }
	void recorderApi.facilitatorAdviceFeedback(props.token, id, helpful).catch(() => undefined)
}
const aiLevelLabel = computed(() => {
	const level = status.value?.ai_facilitator?.level ?? 'off'
	return t(`recorder.recording.ai${level.charAt(0).toUpperCase() + level.slice(1)}`)
})

/* ---- speaking balance (when the engine labels speakers) ---- */
const voices = computed(() => {
	const speaking = status.value?.speaking
	if (!speaking) return []
	return speaking.shares.map((share, index) => ({
		letter: String.fromCharCode(65 + index),
		percent: Math.round(share),
	}))
})

async function load(): Promise<void> {
	try {
		const next = await recorderApi.facilitatorStatus(props.token)
		readAt = Date.now()
		now.value = readAt
		status.value = next
		setLocale(next.assembly.language)
		ingest(next.messages ?? [])
	} catch (err) {
		if (/HTTP 40[14]/.test(err instanceof Error ? err.message : '')) gone.value = true
	}
}

async function leave(): Promise<void> {
	try {
		await recorderApi.facilitatorLeave(props.token)
	} catch {
		/* the session expires by itself */
	}
	emit('forget')
}

onMounted(() => {
	void load()
	poll = window.setInterval(() => void load(), POLL_MS)
	ticker = window.setInterval(() => (now.value = Date.now()), 1000)
	heartbeat = window.setInterval(
		() => void recorderApi.facilitatorHeartbeat(props.token).catch(() => undefined),
		HEARTBEAT_MS,
	)
	void recorderApi.facilitatorHeartbeat(props.token).catch(() => undefined)
})
onBeforeUnmount(() => {
	window.clearInterval(poll)
	window.clearInterval(ticker)
	window.clearInterval(heartbeat)
})
</script>

<template>
	<div class="rc-scroll">
		<div v-if="gone" class="rc-pad rc-center">
			<h1 style="margin-top: 12vh">{{ t('recorder.facilitator.goneTitle') }}</h1>
			<p class="rc-lead">{{ t('recorder.facilitator.goneBody') }}</p>
			<button class="rc-btn rc-subtle" @click="emit('forget')">{{ t('recorder.participant.forget') }}</button>
		</div>

		<div v-else-if="status" class="rc-pad">
			<p class="rc-eyebrow">{{ t('recorder.facilitator.eyebrow') }} · {{ status.assembly.name }}</p>
			<div style="margin: 4px 0 6px">
				<TableBadge :number="status.table_number" :color-key="status.color_key" hero />
			</div>

			<p v-if="status.assembly_closed" class="rc-alert" data-test="closed">{{ t('recorder.facilitator.closed') }}</p>

			<!-- the session: its clock first, then what it is about -->
			<div class="rc-card" style="text-align: left" data-test="session">
				<template v-if="status.round">
					<p class="rc-eyebrow" style="margin-bottom: 2px">
						{{ t('recorder.common.roundNumber', { position: status.round.position }) }}
						<template v-if="status.round.title"> · {{ status.round.title }}</template>
					</p>
					<p v-if="status.round.status === 'ACTIVE'" class="rc-fac-clock" :class="clockClass" data-test="clock">
						{{ clockText }}
					</p>
					<p v-else-if="status.round.status === 'NOT_STARTED'" class="rc-muted" style="margin: 4px 0" data-test="not-running">
						{{ t('recorder.facilitator.notRunning') }}
					</p>
					<p v-else class="rc-muted" style="margin: 4px 0" data-test="ended">{{ t('recorder.facilitator.ended') }}</p>
					<p class="rc-eyebrow" style="margin: 8px 0 0">{{ t('recorder.facilitator.question') }}</p>
					<p class="rc-fac-question" data-test="question">{{ status.round.question }}</p>
					<template v-if="status.round.objective">
						<p class="rc-eyebrow" style="margin: 8px 0 0">{{ t('recorder.facilitator.objective') }}</p>
						<p class="rc-fac-objective">{{ status.round.objective }}</p>
					</template>
				</template>
				<p v-else class="rc-muted" style="margin: 0">{{ t('recorder.facilitator.notRunning') }}</p>
			</div>

			<!-- the AI facilitator's advice, for the facilitator to judge -->
			<div v-if="status.capabilities.ai_facilitator" class="rc-card" style="text-align: left" data-test="advice">
				<p class="rc-eyebrow" style="margin-bottom: 2px">
					{{ t('recorder.facilitator.adviceTitle') }} · {{ t('recorder.facilitator.adviceLevel', { level: aiLevelLabel }) }}
				</p>
				<p v-if="!status.advice.length" class="rc-muted" style="margin: 4px 0 0; font-size: 0.875rem">
					{{ t('recorder.facilitator.adviceNone') }}
				</p>
				<div v-for="item in status.advice" :key="item.id" class="rc-fac-advice" data-test="advice-card">
					<p>{{ item.text }}</p>
					<p v-if="sentAdvice.has(item.id)" class="rc-ok" style="margin: 0; font-size: 0.875rem" data-test="advice-sent">
						✓ {{ t('recorder.facilitator.sentToTable') }}
					</p>
					<div v-else class="rc-fac-advice__actions">
						<button type="button" class="rc-btn rc-subtle" :disabled="adviceBusy === item.id" data-test="advice-dismiss" @click="dismissAdvice(item.id)">
							{{ t('recorder.facilitator.dismiss') }}
						</button>
						<button type="button" class="rc-btn rc-primary" :disabled="adviceBusy === item.id" data-test="advice-send" @click="sendAdvice(item.id)">
							{{ t('recorder.facilitator.sendToTable') }}
						</button>
					</div>
					<div class="rc-message__thumbs" style="margin-top: 8px">
						<template v-if="ratedAdvice[item.id] === undefined">
							<button type="button" class="rc-fac-thumb" data-test="advice-up" @click="rateAdvice(item.id, true)">👍 {{ t('recorder.facilitator.helpful') }}</button>
							<button type="button" class="rc-fac-thumb" data-test="advice-down" @click="rateAdvice(item.id, false)">👎 {{ t('recorder.facilitator.notHelpful') }}</button>
						</template>
						<span v-else class="rc-muted" style="font-size: 0.8125rem">{{ t('recorder.message.thanks') }}</span>
					</div>
				</div>
			</div>

			<!-- messages from the organizer -->
			<div v-if="messages.length" class="rc-card" style="text-align: left" data-test="messages">
				<p class="rc-eyebrow" style="margin-bottom: 2px">{{ t('recorder.facilitator.messagesTitle') }}</p>
				<div v-for="message in messages" :key="message.id" class="rc-fac-message">
					<strong>{{ message.text }}</strong>
					<button type="button" class="rc-help__dismiss" style="float: right" :aria-label="t('recorder.message.dismiss')" @click="dismissMessage(message.id)">×</button>
				</div>
			</div>

			<!-- the people, the consent, the phones -->
			<div class="rc-card" style="text-align: left" data-test="people">
				<p class="rc-eyebrow" style="margin-bottom: 2px">{{ t('recorder.facilitator.people') }}</p>
				<p v-if="status.consent.registered" style="margin: 4px 0 0; font-size: 0.9375rem">
					{{ t('recorder.facilitator.consenting', { consenting: status.consent.consenting, registered: status.consent.registered }) }}
				</p>
				<p v-else class="rc-muted" style="margin: 4px 0 0; font-size: 0.9375rem">{{ t('recorder.facilitator.nobodyRegistered') }}</p>
				<div v-if="status.participants.length" class="rc-fac-people">
					<span v-for="person in status.participants" :key="person.label" :class="{ 'rc-fac-people--no': !person.recording_consent }">
						{{ person.name }}
					</span>
				</div>
				<p class="rc-muted" style="margin: 8px 0 0; font-size: 0.8125rem">
					{{ t('recorder.facilitator.recorders', { count: status.recorders }) }}
				</p>
			</div>

			<!-- speaking balance: anonymous voices, or why there is none -->
			<div class="rc-card" style="text-align: left" data-test="speaking">
				<p class="rc-eyebrow" style="margin-bottom: 2px">{{ t('recorder.facilitator.speakingTitle') }}</p>
				<div v-if="voices.length" class="rc-fac-balance">
					<div v-for="voice in voices" :key="voice.letter" class="rc-fac-balance__row">
						<span>{{ t('recorder.facilitator.voice', { letter: voice.letter }) }}</span>
						<span class="rc-fac-balance__bar"><span class="rc-fac-balance__fill" :style="{ width: voice.percent + '%' }"></span></span>
						<span style="text-align: right">{{ voice.percent }}%</span>
					</div>
				</div>
				<p v-else class="rc-muted" style="margin: 4px 0 0; font-size: 0.875rem">{{ t('recorder.facilitator.speakingUnavailable') }}</p>
			</div>

			<!-- a prompt to the table's phones -->
			<div class="rc-card" style="text-align: left" data-test="prompt">
				<p class="rc-eyebrow" style="margin-bottom: 2px">{{ t('recorder.facilitator.promptTitle') }}</p>
				<p class="rc-muted" style="margin: 2px 0 0; font-size: 0.8125rem">{{ t('recorder.facilitator.promptHint') }}</p>
				<textarea
					v-model="prompt"
					class="rc-fac-textarea"
					rows="2"
					maxlength="300"
					:placeholder="t('recorder.facilitator.promptPlaceholder')"
					data-test="prompt-text"></textarea>
				<button class="rc-btn rc-primary" style="margin-top: 0" :disabled="sending || !prompt.trim()" data-test="send-prompt" @click="send">
					{{ t('recorder.facilitator.send') }}
				</button>
				<p v-if="sentAt" class="rc-ok" style="margin: 6px 0 0; font-size: 0.875rem" data-test="sent">{{ t('recorder.facilitator.sent') }}</p>
				<p v-if="promptFailed" class="rc-alert" style="margin: 6px 0 0">{{ t('recorder.facilitator.promptFailed') }}</p>
			</div>

			<!-- the table's hand, from here -->
			<div v-if="status.assembly.kind !== 'session'" class="rc-card rc-center" data-test="help">
				<p v-if="status.help" class="rc-help__state" :class="{ 'rc-help__state--seen': status.help.acknowledged_at }" role="status">
					<SvgIcon :path="mdiHandBackLeft" :size="16" />
					<span>{{ status.help.acknowledged_at ? t('recorder.help.seen') : t('recorder.help.notified') }}</span>
				</p>
				<button v-else type="button" class="rc-help__btn" data-test="need-help" @click="helpOpen = true">
					<SvgIcon :path="mdiHandBackLeft" :size="16" />
					{{ t('recorder.help.button') }}
				</button>
			</div>

			<!-- this phone -->
			<div class="rc-card" style="text-align: left" data-test="this-phone">
				<p class="rc-eyebrow" style="margin-bottom: 2px">{{ t('recorder.facilitator.thisPhone') }}</p>
				<p v-if="registered" class="rc-ok" style="margin: 4px 0 0; font-size: 0.9375rem" data-test="registered">
					✓ {{ t('recorder.facilitator.registered') }}
				</p>
				<template v-else>
					<p class="rc-muted" style="margin: 2px 0 0; font-size: 0.8125rem">{{ t('recorder.facilitator.registerHint') }}</p>
					<button class="rc-btn" style="margin-top: 6px" :disabled="registering" data-test="register" @click="register">
						{{ t('recorder.facilitator.register') }}
					</button>
				</template>
				<p class="rc-muted" style="margin: 10px 0 0; font-size: 0.8125rem">{{ t('recorder.facilitator.becomeRecorderHint') }}</p>
				<button v-if="!recorderConfirm" class="rc-btn" style="margin-top: 6px" data-test="become-recorder" @click="recorderConfirm = true">
					{{ t('recorder.facilitator.becomeRecorder') }}
				</button>
				<template v-else>
					<button class="rc-btn rc-record" style="margin-top: 6px" :disabled="recorderBusy" data-test="become-recorder-confirm" @click="becomeRecorder">
						{{ t('recorder.facilitator.becomeRecorderConfirm') }}
					</button>
					<button class="rc-btn rc-subtle" @click="recorderConfirm = false">{{ t('recorder.facilitator.cancel') }}</button>
				</template>
			</div>

			<button class="rc-btn rc-subtle" style="margin-top: 10px" data-test="leave" @click="leave">
				{{ t('recorder.facilitator.leave') }}
			</button>
		</div>

		<div v-else class="rc-pad rc-center"><p class="rc-muted">{{ t('recorder.facilitator.connecting') }}</p></div>

		<!-- what kind of help -->
		<div v-if="helpOpen" class="rc-sheet-scrim" @click.self="helpOpen = false">
			<div class="rc-sheet" role="dialog" aria-modal="true">
				<p class="rc-eyebrow rc-center" style="display: block">{{ t('recorder.help.title') }}</p>
				<button v-for="kind in KINDS" :key="kind" type="button" class="rc-btn rc-primary" :disabled="helpBusy" :data-test="`help-${kind}`" @click="askHelp(kind)">
					{{ t(`recorder.help.kind.${kind}`) }}
				</button>
				<button type="button" class="rc-btn rc-subtle" @click="helpOpen = false">{{ t('recorder.help.cancel') }}</button>
			</div>
		</div>
	</div>
</template>

<style scoped>
.rc-pad { padding: 6px 2px calc(12px + env(safe-area-inset-bottom, 0px)); }
.rc-lead { font-size: 1.02rem; line-height: 1.5; margin: 8px 0 0; }
.rc-ok { color: #1e6b3a; }
.rc-fac-thumb {
	background: none;
	border: 1px solid var(--rc-border);
	border-radius: 999px;
	color: inherit;
	font: inherit;
	font-size: 0.8125rem;
	padding: 4px 10px;
	min-height: 32px;
	cursor: pointer;
}
</style>
