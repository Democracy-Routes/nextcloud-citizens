<!--
	SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
	SPDX-License-Identifier: AGPL-3.0-or-later

	What a phone sees after its person declines the recording notice (0.8).
	Nothing is recorded and nothing is sent to the server — this is purely a
	local choice. The person can still take part in the discussion, just not
	through this phone's microphone; "Read it again" goes back to the notice,
	"Scan the code again" returns to the app's start screen.
-->
<script setup lang="ts">
import { useI18n } from 'vue-i18n'

const emit = defineEmits<{ 'read-again': []; 'scan-again': [] }>()

const { t } = useI18n()
</script>

<template>
	<div class="rc-fill">
	<div class="rc-scroll">
		<div class="rc-hero rc-hero--top">
			<h1>{{ t('recorder.declined.title') }}</h1>
			<p class="rc-muted" style="margin-top: 14px">{{ t('recorder.declined.body') }}</p>
			<p class="rc-muted" style="margin-top: 14px">{{ t('recorder.declined.noticeHint') }}</p>
			<button class="rc-btn" style="margin-top: 22px" data-test="read-again" @click="emit('read-again')">
				{{ t('recorder.declined.readAgain') }}
			</button>
			<button class="rc-btn rc-primary" data-test="scan-again" @click="emit('scan-again')">
				{{ t('recorder.declined.scanAgain') }}
			</button>
		</div>
	</div>
	</div>
</template>
