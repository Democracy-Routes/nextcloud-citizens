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
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { setLocale } from '../../i18n'
import { recorderApi, type RegisterNotice } from '../api'
import ConsentForm, { type ConsentFormValue } from './ConsentForm.vue'
import TableBadge from './TableBadge.vue'

const props = defineProps<{ token: string }>()
const emit = defineEmits<{ registered: [participantToken: string] }>()

const { t } = useI18n()

const notice = ref<RegisterNotice | null>(null)
const invalid = ref(false)
const loading = ref(true)
const view = ref<'notice' | 'form'>('notice')
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
			publication_consent: yes,
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
	<div class="rc-scroll">
		<div v-if="loading" class="rc-pad rc-center"><p class="rc-muted">…</p></div>

		<div v-else-if="invalid || !notice" class="rc-pad rc-center">
			<h1 style="margin-top: 12vh">{{ t('recorder.register.invalidTitle') }}</h1>
			<p class="rc-lead">{{ t('recorder.register.invalidBody') }}</p>
		</div>

		<div v-else-if="view === 'form'" class="rc-pad">
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
				@confirm="(value) => submit(value, false)"
				@refuse="(value) => submit(value, true)"
				@cancel="view = 'notice'" />
		</div>

		<div v-else class="rc-pad">
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
			<div class="rc-notice" data-test="notice">
				<p v-for="(paragraph, index) in notice.paragraphs" :key="index">{{ paragraph }}</p>
			</div>
			<button class="rc-btn rc-primary" style="margin-top: 18px" data-test="register" @click="view = 'form'">
				{{ t('recorder.register.button') }}
			</button>
		</div>
	</div>
</template>

<style scoped>
.rc-pad { padding: 6px 2px calc(12px + env(safe-area-inset-bottom, 0px)); }
.rc-lead { font-size: 1.02rem; line-height: 1.5; margin: 8px 0 0; }
</style>
