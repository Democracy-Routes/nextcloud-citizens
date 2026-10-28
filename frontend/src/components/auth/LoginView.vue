<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
/** Sign-in for the standalone mode, with the "forgot password" request. */
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api, ApiError } from '../../api'
import { describeError } from '../../errors'
import type { Account, AuthConfig } from '../../types'
import CzButton from '../ui/CzButton.vue'

const props = defineProps<{ config: AuthConfig }>()
const emit = defineEmits<{ 'signed-in': [account: Account] }>()
const { t } = useI18n()

const username = ref('')
const password = ref('')
const busy = ref(false)
const error = ref('')

const forgot = ref(false)
const email = ref('')
const sent = ref(false)

async function submit(): Promise<void> {
	if (busy.value) return
	busy.value = true
	error.value = ''
	try {
		const account = await api.login({ username: username.value.trim(), password: password.value })
		password.value = ''
		emit('signed-in', account)
	} catch (err) {
		// the server's own sentence ("Wrong username or password"); describeError
		// would call a 401 "no permission"
		error.value = err instanceof ApiError ? err.message : describeError(err).message
	} finally {
		busy.value = false
	}
}

async function sendReset(): Promise<void> {
	if (busy.value || !email.value.trim()) return
	busy.value = true
	error.value = ''
	try {
		await api.requestReset(email.value.trim())
		sent.value = true
	} catch (err) {
		error.value = describeError(err).message
	} finally {
		busy.value = false
	}
}

function openForgot(): void {
	forgot.value = true
	error.value = ''
}

function backToLogin(): void {
	forgot.value = false
	sent.value = false
	error.value = ''
}
</script>

<template>
	<main class="cz-card" style="max-width: 400px; margin: 10vh auto; padding: 24px" data-test="login-view">
		<h2>{{ t('organizer.shell.auth.title') }}</h2>

		<form v-if="!forgot" @submit.prevent="submit">
			<p class="cz-muted">{{ t('organizer.shell.auth.lead') }}</p>
			<div v-if="error" class="cz-error" data-test="login-error">{{ error }}</div>
			<div class="cz-field">
				<label for="cz-login-username">{{ t('organizer.shell.auth.username') }}</label>
				<input id="cz-login-username" v-model="username" type="text" autocomplete="username" required />
			</div>
			<div class="cz-field">
				<label for="cz-login-password">{{ t('organizer.shell.auth.password') }}</label>
				<input id="cz-login-password" v-model="password" type="password" autocomplete="current-password" required />
			</div>
			<button
				type="submit"
				class="cz-btn cz-btn--primary cz-btn--wide"
				data-test="login-submit"
				:disabled="busy || !username || !password">
				{{ busy ? t('organizer.shell.auth.signingIn') : t('organizer.shell.auth.signIn') }}
			</button>
			<p style="margin-top: 14px">
				<a href="#" data-test="login-forgot" @click.prevent="openForgot">{{ t('organizer.shell.auth.forgot') }}</a>
			</p>
		</form>

		<form v-else @submit.prevent="sendReset">
			<h3>{{ t('organizer.shell.auth.forgotTitle') }}</h3>
			<p v-if="!props.config.mail" class="cz-muted" data-test="reset-by-admin">
				{{ t('organizer.shell.auth.resetByAdmin') }}
			</p>
			<template v-else-if="!sent">
				<p class="cz-muted">{{ t('organizer.shell.auth.forgotLead') }}</p>
				<div v-if="error" class="cz-error">{{ error }}</div>
				<div class="cz-field">
					<label for="cz-login-email">{{ t('organizer.shell.auth.email') }}</label>
					<input id="cz-login-email" v-model="email" type="email" autocomplete="email" required />
				</div>
				<button type="submit" class="cz-btn cz-btn--primary cz-btn--wide" data-test="reset-submit" :disabled="busy || !email">
					{{ t('organizer.shell.auth.sendLink') }}
				</button>
			</template>
			<p v-else data-test="reset-sent">{{ t('organizer.shell.auth.resetSent') }}</p>
			<p style="margin-top: 14px">
				<CzButton variant="tertiary" small @click="backToLogin">{{ t('organizer.shell.auth.backToSignIn') }}</CzButton>
			</p>
		</form>
	</main>
</template>
