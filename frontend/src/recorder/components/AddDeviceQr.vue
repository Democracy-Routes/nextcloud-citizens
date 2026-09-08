<!--
	SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
	SPDX-License-Identifier: AGPL-3.0-or-later

	The room's shared join QR, shown on a phone that already joined.

	Plenary rooms share one code, so adding a device is just scanning it again
	— and the nearest copy of the code is the phone beside you, not the
	organizer's screen. The QR sits on a white card whatever the theme: the
	quiet zone around a QR must stay light or scanners misread it.
-->
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { recorderApi } from '../api'

const props = defineProps<{ token: string }>()

const { t } = useI18n()
const qrSrc = ref('')
const unavailable = ref(false)
const loading = ref(true)

onMounted(async () => {
	try {
		const result = await recorderApi.inviteQr(props.token)
		if (result.available && result.qr_svg) {
			// data URI, not v-html: an image cannot execute script
			qrSrc.value = `data:image/svg+xml;base64,${btoa(result.qr_svg)}`
		} else {
			unavailable.value = true
		}
	} catch {
		unavailable.value = true
	} finally {
		loading.value = false
	}
})
</script>

<template>
	<div class="rc-card rc-center">
		<p class="rc-eyebrow">{{ t('recorder.addDevice.title') }}</p>
		<template v-if="qrSrc">
			<div class="rc-qr-card">
				<img class="rc-qr" :src="qrSrc" alt="QR code to join this room" />
			</div>
			<p class="rc-muted" style="font-size: 0.845rem; margin: 0">
				{{ t('recorder.addDevice.hint') }}
			</p>
		</template>
		<p v-else-if="unavailable" class="rc-muted" style="font-size: 0.875rem; margin: 0">
			{{ t('recorder.addDevice.unavailable') }}
		</p>
		<p v-else-if="loading" class="rc-muted" style="font-size: 0.875rem; margin: 0">…</p>
	</div>
</template>
