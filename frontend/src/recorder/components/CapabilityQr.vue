<!--
	SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
	SPDX-License-Identifier: AGPL-3.0-or-later

	A code this phone makes for the next phone — and says what it means.

	The phone that already joined decides: "add a recorder to this table" or
	"add a new table". The next phone scans the code and follows it; it never
	picks a role. The intent is printed above the code so nobody holds up the
	wrong one. Codes are short-lived and single-use (the server enforces both);
	the countdown here is a courtesy, and an expired code offers a fresh one.

	The QR sits on a white card whatever the theme: the quiet zone around a QR
	must stay light or scanners misread it. Rendered as an image, never as
	injected markup.
-->
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { recorderApi, type CapabilityPurpose } from '../api'
import TableBadge from './TableBadge.vue'

const props = defineProps<{
	token: string
	purpose: CapabilityPurpose
	tableNumber: number
	colorKey?: string | null
	roundId?: string | null
}>()
const emit = defineEmits<{ close: [] }>()

const { t } = useI18n()

const qrSrc = ref('')
const expiresAt = ref<number | null>(null)
const unavailable = ref(false)
const loading = ref(true)
const now = ref(Date.now())
let ticker = 0

const remainingMinutes = computed(() => {
	if (expiresAt.value === null) return 0
	return Math.max(0, Math.ceil((expiresAt.value - now.value) / 60_000))
})
const expired = computed(() => expiresAt.value !== null && now.value >= expiresAt.value)

async function make(): Promise<void> {
	loading.value = true
	unavailable.value = false
	qrSrc.value = ''
	try {
		const card = await recorderApi.createCapability(props.token, props.purpose, props.roundId)
		// data URI, not v-html: an image cannot execute script
		qrSrc.value = `data:image/svg+xml;base64,${btoa(card.qr_svg)}`
		expiresAt.value = Date.parse(card.expires_at)
		now.value = Date.now()
	} catch {
		unavailable.value = true
	} finally {
		loading.value = false
	}
}

onMounted(() => {
	void make()
	ticker = window.setInterval(() => (now.value = Date.now()), 15_000)
})
onBeforeUnmount(() => window.clearInterval(ticker))
</script>

<template>
	<div class="rc-card rc-center rc-capability">
		<p class="rc-eyebrow" style="margin-bottom: 4px">
			{{ purpose === 'ADD_TABLE' ? t('recorder.table.addTableTitle') : t('recorder.table.addRecorderTitle') }}
		</p>
		<TableBadge v-if="purpose === 'ADD_RECORDER_TO_TABLE'" :number="tableNumber" :color-key="colorKey" />

		<template v-if="qrSrc && !expired">
			<div class="rc-qr-card">
				<img class="rc-qr" :src="qrSrc" :alt="t('recorder.table.qrAlt')" />
			</div>
			<p class="rc-muted" style="font-size: 0.845rem; margin: 0">
				{{ purpose === 'ADD_TABLE' ? t('recorder.table.addTableHint') : t('recorder.table.addRecorderHint') }}
			</p>
			<p class="rc-muted" style="font-size: 0.8rem; margin: 6px 0 0">
				{{ t('recorder.table.expiresIn', { minutes: remainingMinutes }, remainingMinutes) }}
			</p>
		</template>
		<template v-else-if="expired">
			<p class="rc-muted" style="font-size: 0.875rem; margin: 0">{{ t('recorder.table.expired') }}</p>
			<button class="rc-btn" style="margin-top: 10px" @click="make">{{ t('recorder.table.newCode') }}</button>
		</template>
		<p v-else-if="unavailable" class="rc-muted" style="font-size: 0.875rem; margin: 0">
			{{ t('recorder.table.unavailable') }}
		</p>
		<p v-else-if="loading" class="rc-muted" style="font-size: 0.875rem; margin: 0">…</p>

		<button class="rc-btn rc-subtle" style="margin-top: 8px" @click="emit('close')">
			{{ t('recorder.table.close') }}
		</button>
	</div>
</template>
