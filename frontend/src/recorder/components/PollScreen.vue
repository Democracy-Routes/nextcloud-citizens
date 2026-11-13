<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { recorderApi } from '../api'

/*
 * The Polis poll of this assembly: a QR to scan with one's own phone and the
 * link itself. The QR is an <img> with a data URI, never injected markup.
 */

const props = defineProps<{ token: string }>()
const emit = defineEmits<{ back: [] }>()

const { t } = useI18n()
const url = ref('')
const qrSrc = ref('')
const error = ref('')
const loading = ref(true)

onMounted(async () => {
	try {
		const result = await recorderApi.pollQr(props.token)
		if (result.available && result.url) {
			url.value = result.url
			if (result.qr_svg) qrSrc.value = `data:image/svg+xml;base64,${btoa(result.qr_svg)}`
		}
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err)
	} finally {
		loading.value = false
	}
})
</script>

<template>
	<div class="rc-fill">
		<div class="rc-scroll">
			<div v-if="error" class="rc-alert">{{ error }}</div>
			<div class="rc-card rc-center" data-test="poll-screen">
				<h1 style="font-size: 1.25rem">{{ t('recorder.poll.title') }}</h1>
				<p class="rc-muted" style="margin: 6px 0 12px">{{ t('recorder.poll.lead') }}</p>
				<div v-if="qrSrc" class="rc-qr-card">
					<img class="rc-qr" :src="qrSrc" alt="QR code of the poll" data-test="poll-qr" />
				</div>
				<template v-if="url">
					<a class="rc-btn rc-primary" :href="url" target="_blank" rel="noopener" data-test="poll-link">
						{{ t('recorder.poll.open') }}
					</a>
					<p class="rc-muted" style="font-size: 0.8125rem; word-break: break-all; margin: 8px 0 0">{{ url }}</p>
				</template>
				<p v-else-if="loading" class="rc-muted">…</p>
			</div>
			<button class="rc-btn rc-subtle" data-test="poll-back" @click="emit('back')">
				{{ t('recorder.poll.back') }}
			</button>
		</div>
	</div>
</template>
