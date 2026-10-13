<!--
	SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
	SPDX-License-Identifier: AGPL-3.0-or-later

	Registration on a person's own phone (recorder.html#/register/<token>).
	The table's notice screen showed a code; this phone scanned it. The code
	says which event and which table, so nobody types a table; the person
	reads the same server-rendered notice and fills the same form as on the
	shared phone. Registering hands the phone a bearer for the person's own
	page (ParticipantPage), kept in this browser.
-->
<script setup lang="ts">
import { type ComponentPublicInstance, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { setLocale } from '../../i18n'
import { recorderApi, type RegisterNotice } from '../api'
import ConsentForm, { type ConsentFormValue } from './ConsentForm.vue'
import DeclinedScreen from './DeclinedScreen.vue'
import TableBadge from './TableBadge.vue'

const props = defineProps<{ token: string }>()
const emit = defineEmits<{ registered: [participantToken: string]; 'scan-again': [] }>()

const { t } = useI18n()

const notice = ref<RegisterNotice | null>(null)
const invalid = ref(false)
const loading = ref(true)
const view = ref<'notice' | 'form' | 'declined'>('notice')
const busy = ref(false)
const failed = ref('')

onMounted(async () => {
	try {
		notice.value = await recorderApi.registerNotice(props.token)
		// the event's language, as on the table's phone
		setLocale(notice.value.assembly.language)
	} catch {
		invalid.value = true
	} finally {
		loading.value = false
	}
})

/* ---- scroll-gated Register: the notice must be read to its end before the
 * one button that moves on can be reached — same gate as the table phone's,
 * see ConsentScreen. ---- */
const frameEl = ref<HTMLElement | null>(null)
const readToEnd = ref(false)
let frameObserver: ResizeObserver | undefined

function checkReadToEnd(): void {
	const el = frameEl.value
	if (!el) return
	readToEnd.value = el.scrollTop + el.clientHeight >= el.scrollHeight - 8
}

/** A function ref: this view is only ever entered once per phone (there is no
 * "back to notice" once registered), but it still needs the first-mount
 * check, which a plain ref would miss if it fires before the element paints.
 * Typed loosely to match Vue's own function ref signature; this is always a
 * plain <div>, never a component. */
function attachFrame(el: Element | ComponentPublicInstance | null): void {
	frameObserver?.disconnect()
	frameObserver = undefined
	frameEl.value = el as HTMLElement | null
	if (!frameEl.value) return
	checkReadToEnd()
	if (typeof ResizeObserver === 'undefined') return
	frameObserver = new ResizeObserver(checkReadToEnd)
	frameObserver.observe(frameEl.value)
}
onBeforeUnmount(() => frameObserver?.disconnect())

async function submit(value: ConsentFormValue, refuse: boolean): Promise<void> {
	if (!notice.value || busy.value) return
	busy.value = true
	failed.value = ''
	try {
		const yes = !refuse && value.accepted
		const result = await recorderApi.registerSelf(props.token, {
			name: value.name,
			email: value.email,
			notice_hash: notice.value.hash,
			notice_read: true,
			recording_consent: yes,
			transcription_consent: yes,
			analysis_consent: yes,
			publication_consent: yes && value.quotations,
		})
		emit('registered', result.participant_token)
	} catch (err) {
		const message = err instanceof Error ? err.message : String(err)
		const stale = /NOTICE_CHANGED|notice has changed/i.test(message)
		failed.value = stale ? t('recorder.consent.form.stale') : t('recorder.consent.form.failed')
		if (stale) {
			try {
				notice.value = await recorderApi.registerNotice(props.token)
			} catch {
				/* the next attempt will say */
			}
		}
	} finally {
		busy.value = false
	}
}
</script>

<template>
	<div v-if="loading" class="rc-scroll rc-pad rc-center"><p class="rc-muted">…</p></div>

	<div v-else-if="invalid || !notice" class="rc-scroll rc-pad rc-center">
		<h1 style="margin-top: 12vh">{{ t('recorder.register.invalidTitle') }}</h1>
		<p class="rc-lead">{{ t('recorder.register.invalidBody') }}</p>
	</div>

	<!-- declined before even registering: nothing was sent to the server -->
	<DeclinedScreen
		v-else-if="view === 'declined'"
		@read-again="view = 'notice'"
		@scan-again="emit('scan-again')" />

	<div v-else-if="view === 'form'" class="rc-scroll rc-pad">
		<h1>{{ t('recorder.register.formTitle') }}</h1>
		<p class="rc-muted" style="margin: 6px 0 0">
			{{
				notice.table_number
					? t('recorder.register.formLead', { number: notice.table_number })
					: t('recorder.register.formLeadAssembly')
			}}
		</p>
		<ConsentForm
			self
			:busy="busy"
			:failed="failed"
			:acceptance="notice.acceptance"
			:acceptance-quotations="notice.acceptance_quotations"
			@confirm="(value) => submit(value, false)"
			@refuse="(value) => submit(value, true)"
			@cancel="view = 'notice'" />
	</div>

	<!-- the notice: a fixed column (header, a scroll-gated frame, a pinned
	     footer) so Register cannot be reached without scrolling to the end -->
	<div v-else class="rc-fill">
		<p class="rc-eyebrow">{{ notice.assembly.name }}</p>
		<!-- a table's code names the table; the assembly's pre-registration
		     link names nothing — the door seats people by name -->
		<div v-if="notice.table_number" style="margin: 4px 0 10px">
			<TableBadge :number="notice.table_number" :color-key="notice.color_key" />
		</div>
		<h1>
			{{
				notice.table_number
					? t('recorder.register.title', { number: notice.table_number })
					: t('recorder.register.titleAssembly', { name: notice.assembly.name })
			}}
		</h1>
		<p class="rc-lead">{{ notice.table_number ? t('recorder.register.lead') : t('recorder.register.leadAssembly') }}</p>

		<div :ref="attachFrame" class="rc-notice-frame" data-test="notice-frame" @scroll="checkReadToEnd">
			<div class="rc-notice" data-test="notice">
				<p v-for="(paragraph, index) in notice.paragraphs" :key="index">{{ paragraph }}</p>
			</div>
		</div>

		<div class="rc-consent__footer">
			<p v-if="!readToEnd" class="rc-muted rc-consent__hint" data-test="scroll-hint">{{ t('recorder.consent.scrollToEnd') }}</p>
			<div class="rc-consent__actions">
				<button
					class="rc-btn"
					:class="{ 'rc-primary': readToEnd }"
					:disabled="!readToEnd"
					data-test="register"
					@click="view = 'form'">
					{{ t('recorder.register.button') }}
				</button>
				<button class="rc-btn rc-subtle" data-test="deny" @click="view = 'declined'">
					{{ t('recorder.consent.deny') }}
				</button>
			</div>
		</div>
	</div>
</template>

<style scoped>
.rc-pad { padding: 6px 2px calc(12px + env(safe-area-inset-bottom, 0px)); }
.rc-lead { font-size: 1.02rem; line-height: 1.5; margin: 8px 0 0; }
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
.rc-consent__hint { margin: 8px 0 0; font-size: 0.875rem; }
.rc-consent__actions { display: flex; gap: 10px; flex-wrap: wrap; }
.rc-consent__actions .rc-btn { width: auto; flex: 0 1 auto; margin-top: 0; padding: 10px 20px; }
</style>
