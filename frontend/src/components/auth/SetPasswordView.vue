<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
/** The landing of an invitation or reset link: choose a password, be signed in. */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api, ApiError } from '../../api'
import { describeError } from '../../errors'
import type { Account } from '../../types'
import CzButton from '../ui/CzButton.vue'

const MIN_LENGTH = 10

const props = defineProps<{ token: string }>()
const emit = defineEmits<{ 'signed-in': [account: Account]; 'to-login': [] }>()
const { t } = useI18n()

const password = ref('')
const again = ref('')
const busy = ref(false)
const error = ref('')

const tooShort = computed(() => password.value.length > 0 && password.value.length < MIN_LENGTH)
const mismatch = computed(() => again.value.length > 0 && again.value !== password.value)
const ready = computed(() => password.value.length >= MIN_LENGTH && password.value === again.value)

async function submit(): Promise<void> {
	if (busy.value || !ready.value) return
	busy.value = true
	error.value = ''
	try {
		const account = await api.setPassword({ token: props.token, password: password.value })
		emit('signed-in', account)
	} catch (err) {
		error.value = err instanceof ApiError && err.status < 500 ? err.message : describeError(err).message
	} finally {
		busy.value = false
	}
}
</script>

<template>
	<main class="cz-card" style="max-width: 400px; margin: 10vh auto; padding: 24px" data-test="set-password-view">
		<h2>{{ t('organizer.shell.auth.setTitle') }}</h2>
		<p class="cz-muted">{{ t('organizer.shell.auth.setLead', { min: MIN_LENGTH }) }}</p>
		<form @submit.prevent="submit">
			<div v-if="error" class="cz-error" data-test="set-password-error">{{ error }}</div>
			<div class="cz-field">
				<label for="cz-new-password">{{ t('organizer.shell.auth.newPassword') }}</label>
				<input id="cz-new-password" v-model="password" type="password" autocomplete="new-password" required />
				<p v-if="tooShort" class="cz-muted" style="font-size: 0.78rem">
					{{ t('organizer.shell.auth.tooShort', { min: MIN_LENGTH }) }}
				</p>
			</div>
			<div class="cz-field">
				<label for="cz-new-password2">{{ t('organizer.shell.auth.repeatPassword') }}</label>
				<input id="cz-new-password2" v-model="again" type="password" autocomplete="new-password" required />
				<p v-if="mismatch" class="cz-muted" style="font-size: 0.78rem">
					{{ t('organizer.shell.auth.mismatch') }}
				</p>
			</div>
			<button type="submit" class="cz-btn cz-btn--primary cz-btn--wide" data-test="set-password-submit" :disabled="busy || !ready">
				{{ t('organizer.shell.auth.setSubmit') }}
			</button>
		</form>
		<p style="margin-top: 14px">
			<CzButton variant="tertiary" small @click="emit('to-login')">{{ t('organizer.shell.auth.backToSignIn') }}</CzButton>
		</p>
	</main>
</template>
