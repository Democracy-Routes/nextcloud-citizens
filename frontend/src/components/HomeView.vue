<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import { mdiMicrophone, mdiPlayCircleOutline } from '@mdi/js'
import { useI18n } from 'vue-i18n'
import CzButton from './ui/CzButton.vue'
import SvgIcon from './ui/SvgIcon.vue'

const { t } = useI18n()

/** Two ways in, and Import as a footer link. Record now is the fastest: a
 * Session with one table, and this very device as its recorder. Create a
 * session is the one wizard; a second session in it makes a multi-session event. */
defineProps<{
	/** a Record now request is in flight */
	recording: boolean
	/** the recorder link of a Session just made by Record now, when the browser
	 * would not open it in a new tab by itself */
	recorderUrl: string
	error: string
}>()

const emit = defineEmits<{ recordNow: []; createSession: []; importSession: [] }>()
</script>

<template>
	<div class="cz-page cz-home">
		<h2 class="cz-home__title">{{ t('organizer.shell.home.title') }}</h2>
		<p class="cz-home__hint cz-muted">
			{{ t('organizer.shell.home.hint') }}
		</p>

		<div v-if="error" class="cz-error">{{ error }}</div>

		<div v-if="recorderUrl" class="cz-card cz-home__ready">
			<strong>{{ t('organizer.shell.home.readyTitle') }}</strong>
			<p class="cz-muted" style="margin: 4px 0 10px">
				{{ t('organizer.shell.home.readyBody') }}
			</p>
			<a class="cz-home__link" :href="recorderUrl" target="_blank" rel="noopener">{{ t('organizer.shell.home.openRecorder') }}</a>
		</div>

		<div class="cz-home__actions">
			<button class="cz-home__action cz-home__action--primary" :disabled="recording" @click="emit('recordNow')">
				<SvgIcon :path="mdiMicrophone" :size="28" />
				<span class="cz-home__action-name">{{ recording ? t('organizer.shell.home.preparing') : t('organizer.shell.home.recordNow') }}</span>
				<span class="cz-home__action-hint">{{ t('organizer.shell.home.recordNowHint') }}</span>
			</button>
			<button class="cz-home__action" @click="emit('createSession')">
				<SvgIcon :path="mdiPlayCircleOutline" :size="28" />
				<span class="cz-home__action-name">{{ t('organizer.shell.home.createSession') }}</span>
				<span class="cz-home__action-hint">{{ t('organizer.shell.home.createSessionHint') }}</span>
			</button>
		</div>

		<div class="cz-home__foot">
			<CzButton variant="tertiary" small data-test="home-import" :title="t('organizer.shell.home.importSessionHint')" @click="emit('importSession')">{{ t('organizer.shell.home.importSession') }}</CzButton>
		</div>
	</div>
</template>
