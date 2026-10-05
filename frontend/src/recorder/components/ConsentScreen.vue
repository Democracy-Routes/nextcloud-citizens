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
 * phone: name (email optional), the ticks, Confirm. A refusal is recorded
 * too. The record is individual; nothing here is one tick for the table.
 *
 * 'required' assemblies continue only once one person here has consented
 * (the server enforces the same rule where recording starts); 'optional'
 * ones continue at once. A server older than 0.7 has no notice endpoint:
 * the screen then falls back to the table-level text it always showed.
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { recorderApi, type ConsentNotice, type DataHandling, type TableConsent } from '../api'
import TableBadge from './TableBadge.vue'

const props = defineProps<{
	token: string
	handling: DataHandling | null
	tableNumber: number
	colorKey?: string | null
}>()
const emit = defineEmits<{ accept: [table: TableConsent | null] }>()

const { t } = useI18n()

const notice = ref<ConsentNotice | null>(null)
const legacy = ref(false)
const loading = ref(true)
const view = ref<'notice' | 'form' | 'added'>('notice')
const busy = ref(false)
const failed = ref('')
const added = ref<{ name: string; consented: boolean } | null>(null)
const table = ref<TableConsent | null>(null)

/** Somebody at the table objects (legacy screen only). Consent that offers
 * only one button is not consent. */
const declined = ref(false)

const form = ref({
	name: '',
	email: '',
	read: false,
	recording: false,
	transcription: false,
	analysis: false,
	publication: false,
})

async function load(): Promise<void> {
	loading.value = true
	try {
		notice.value = await recorderApi.consentNotice(props.token)
		legacy.value = false
	} catch {
		legacy.value = true // a server older than 0.7, or a blink: the old text
	} finally {
		loading.value = false
	}
}
onMounted(load)

const consenting = computed(
	() => notice.value?.participants.filter((p) => p.recording_consent).length ?? 0,
)
const required = computed(() => notice.value?.mode === 'required')
const canContinue = computed(() => legacy.value || !required.value || consenting.value > 0)
const canConfirm = computed(
	() => form.value.name.trim().length > 0 && form.value.read && form.value.recording,
)

function startForm(): void {
	form.value = {
		name: '', email: '', read: false, recording: false,
		transcription: false, analysis: false, publication: false,
	}
	failed.value = ''
	view.value = 'form'
}

async function submit(refuse = false): Promise<void> {
	if (!notice.value || busy.value) return
	const name = form.value.name.trim()
	if (!name) return
	busy.value = true
	failed.value = ''
	try {
		const result = await recorderApi.registerParticipant(props.token, {
			name,
			email: form.value.email.trim(),
			notice_hash: notice.value.hash,
			notice_read: refuse ? form.value.read : true,
			recording_consent: refuse ? false : form.value.recording,
			transcription_consent: refuse ? false : form.value.transcription,
			analysis_consent: refuse ? false : form.value.analysis,
			publication_consent: refuse ? false : form.value.publication,
		})
		table.value = result.table
		added.value = { name: result.participant.name, consented: result.can_record }
		// the roster, without a second round-trip
		notice.value = {
			...notice.value,
			participants: [
				...notice.value.participants,
				{ label: result.participant.label, name: result.participant.name, recording_consent: result.can_record },
			],
		}
		view.value = 'added'
	} catch (err) {
		const message = err instanceof Error ? err.message : String(err)
		failed.value = /NOTICE_CHANGED|notice has changed/i.test(message)
			? t('recorder.consent.form.stale')
			: t('recorder.consent.form.failed')
		if (/NOTICE_CHANGED|notice has changed/i.test(message)) await load()
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
	<div class="rc-scroll">
		<!-- one person registering -->
		<div v-if="view === 'form' && notice" class="rc-pad">
			<h1>{{ t('recorder.consent.form.title') }}</h1>
			<p class="rc-muted" style="margin: 6px 0 0">{{ t('recorder.consent.form.lead') }}</p>
			<label class="rc-field">
				<span>{{ t('recorder.consent.form.name') }}</span>
				<input v-model="form.name" type="text" autocomplete="off" maxlength="200" data-test="name" />
			</label>
			<label class="rc-field">
				<span>{{ t('recorder.consent.form.email') }}</span>
				<input v-model="form.email" type="email" autocomplete="off" maxlength="200" data-test="email" />
			</label>
			<div class="rc-ticks">
				<label class="rc-tick"><input v-model="form.read" type="checkbox" data-test="read" /><span>{{ t('recorder.consent.form.read') }}</span></label>
				<label class="rc-tick"><input v-model="form.recording" type="checkbox" data-test="recording" /><span>{{ t('recorder.consent.form.recording') }}</span></label>
				<label class="rc-tick"><input v-model="form.transcription" type="checkbox" data-test="transcription" /><span>{{ t('recorder.consent.form.transcription') }}</span></label>
				<label class="rc-tick"><input v-model="form.analysis" type="checkbox" data-test="analysis" /><span>{{ t('recorder.consent.form.analysis') }}</span></label>
				<label class="rc-tick"><input v-model="form.publication" type="checkbox" data-test="publication" /><span>{{ t('recorder.consent.form.publication') }}</span></label>
			</div>
			<p v-if="failed" class="rc-alert">{{ failed }}</p>
			<button class="rc-btn rc-primary" :disabled="!canConfirm || busy" data-test="confirm" @click="submit(false)">
				{{ t('recorder.consent.form.confirm') }}
			</button>
			<button class="rc-btn" :disabled="!form.name.trim() || busy" data-test="refuse" @click="submit(true)">
				{{ t('recorder.consent.form.refuse') }}
			</button>
			<button class="rc-btn rc-subtle" :disabled="busy" @click="view = 'notice'">
				{{ t('recorder.consent.form.cancel') }}
			</button>
		</div>

		<!-- one person done -->
		<div v-else-if="view === 'added' && added" class="rc-pad rc-center">
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
			<p v-if="!canContinue" class="rc-muted rc-consent__hint">{{ t('recorder.consent.requiredHint') }}</p>
		</div>

		<!-- the legacy table-level screen: somebody objected -->
		<div v-else-if="legacy && declined" class="rc-pad">
			<h1>{{ t('recorder.consent.declinedTitle') }}</h1>
			<p class="rc-lead">{{ t('recorder.consent.declinedBody') }}</p>
			<button class="rc-btn" @click="declined = false">
				{{ t('recorder.consent.declinedBack') }}
			</button>
		</div>

		<!-- the notice -->
		<div v-else class="rc-pad">
			<div class="rc-consent__head">
				<TableBadge :number="tableNumber" :color-key="colorKey" />
			</div>
			<h1>{{ t('recorder.consent.title', { number: tableNumber }) }}</h1>
			<p class="rc-lead">{{ t('recorder.consent.lead') }}</p>

			<p v-if="loading" class="rc-muted">…</p>
			<template v-else-if="notice">
				<div class="rc-notice" data-test="notice">
					<p v-for="(paragraph, index) in notice.paragraphs" :key="index">{{ paragraph }}</p>
				</div>

				<h2 class="rc-consent__roster-title">{{ t('recorder.consent.registeredTitle') }}</h2>
				<ul v-if="notice.participants.length" class="rc-roster" data-test="roster">
					<li v-for="person in notice.participants" :key="person.label">
						<span>{{ person.name }}</span>
						<span :class="person.recording_consent ? 'rc-roster__yes' : 'rc-roster__no'">
							{{ person.recording_consent ? t('recorder.consent.consented') : t('recorder.consent.refusedNote') }}
						</span>
					</li>
				</ul>
				<p v-else class="rc-muted" style="margin: 0">{{ t('recorder.consent.none') }}</p>

				<button class="rc-btn" style="margin-top: 16px" data-test="add" @click="startForm">
					{{ t('recorder.consent.add') }}
				</button>
				<button class="rc-btn rc-primary" :disabled="!canContinue" data-test="continue" @click="accept">
					{{ t('recorder.consent.continue') }}
				</button>
				<p v-if="!canContinue" class="rc-muted rc-consent__hint">{{ t('recorder.consent.requiredHint') }}</p>
			</template>

			<!-- a server without the notice endpoint: the table-level text -->
			<template v-else>
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
			</template>
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
.rc-consent__head { margin: 4px 0 10px; }
.rc-notice {
	margin: 14px 0 0;
	padding: 12px 14px;
	border: 1px solid var(--rc-border);
	border-radius: 12px;
	background: var(--rc-surface);
	font-size: 0.9375rem;
	line-height: 1.5;
}
.rc-notice p { margin: 0; }
.rc-notice p + p { margin-top: 8px; }
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
.rc-consent__hint { margin: 8px 0 0; font-size: 0.875rem; }
.rc-consent {
	margin: 18px 0 0;
	padding-left: 20px;
	line-height: 1.55;
}
.rc-consent li + li { margin-top: 10px; }
.rc-consent__ask { margin: 20px 0 18px; }
.rc-field {
	display: block;
	margin: 16px 0 0;
}
.rc-field span {
	display: block;
	font-size: 0.8125rem;
	color: var(--rc-muted);
	margin-bottom: 4px;
}
.rc-field input {
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
.rc-ticks { margin: 18px 0 8px; }
.rc-tick {
	display: flex;
	align-items: flex-start;
	gap: 12px;
	padding: 10px 0;
	border-bottom: 1px solid var(--rc-border);
	line-height: 1.4;
}
.rc-tick input {
	width: 24px;
	height: 24px;
	flex: 0 0 auto;
	margin: 0;
}
</style>
