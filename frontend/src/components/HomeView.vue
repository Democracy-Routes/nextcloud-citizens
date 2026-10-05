<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import { mdiAccountGroup, mdiMicrophone, mdiPlayCircleOutline } from '@mdi/js'
import CzButton from './ui/CzButton.vue'
import SvgIcon from './ui/SvgIcon.vue'

/** The three ways in. Record now is the fastest: a Session with one table,
 * and this very device as its recorder. Nothing here asks for an assembly. */
defineProps<{
	/** a Record now request is in flight */
	recording: boolean
	/** the recorder link of a Session just made by Record now, when the browser
	 * would not open it in a new tab by itself */
	recorderUrl: string
	error: string
}>()

const emit = defineEmits<{ recordNow: []; startSession: []; createAssembly: [] }>()
</script>

<template>
	<div class="cz-page cz-home">
		<h2 class="cz-home__title">Citizens</h2>
		<p class="cz-home__hint cz-muted">
			Record a discussion, run a Session at one or more tables, or organize a whole assembly.
		</p>

		<div v-if="error" class="cz-error">{{ error }}</div>

		<div v-if="recorderUrl" class="cz-card cz-home__ready">
			<strong>Your recorder is ready.</strong>
			<p class="cz-muted" style="margin: 4px 0 10px">
				The browser did not open it by itself — open it here, on this phone.
			</p>
			<a class="cz-home__link" :href="recorderUrl" target="_blank" rel="noopener">Open the recorder</a>
		</div>

		<div class="cz-home__actions">
			<button class="cz-home__action cz-home__action--primary" :disabled="recording" @click="emit('recordNow')">
				<SvgIcon :path="mdiMicrophone" :size="28" />
				<span class="cz-home__action-name">{{ recording ? 'Preparing…' : 'Record now' }}</span>
				<span class="cz-home__action-hint">One table, this phone. Start recording in seconds.</span>
			</button>
			<button class="cz-home__action" @click="emit('startSession')">
				<SvgIcon :path="mdiPlayCircleOutline" :size="28" />
				<span class="cz-home__action-name">Start a Session</span>
				<span class="cz-home__action-hint">A question, an objective, one or more tables with QR codes.</span>
			</button>
			<button class="cz-home__action" @click="emit('createAssembly')">
				<SvgIcon :path="mdiAccountGroup" :size="28" />
				<span class="cz-home__action-name">Create an Assembly</span>
				<span class="cz-home__action-hint">An organized event: participants, several rounds, a full report.</span>
			</button>
		</div>

		<div class="cz-home__foot">
			<CzButton variant="tertiary" small @click="emit('createAssembly')">Open the assembly wizard</CzButton>
		</div>
	</div>
</template>
