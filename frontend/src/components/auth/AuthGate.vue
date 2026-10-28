<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
/** Decides what the organizer shows first.
 *
 * Nextcloud mode: straight to the app, as before. Standalone mode: the
 * set-password page when the URL carries a link's token, the login view when
 * nobody is signed in, the app otherwise. A 401 from any later request (an
 * expired session) brings the login view back instead of an error banner.
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api, ApiError, setUnauthorizedHandler } from '../../api'
import { auth } from '../../auth'
import { setLocale } from '../../i18n'
import type { Account } from '../../types'
import App from '../../App.vue'
import CzButton from '../ui/CzButton.vue'
import LoginView from './LoginView.vue'
import SetPasswordView from './SetPasswordView.vue'

type Stage = 'loading' | 'set-password' | 'login' | 'app' | 'failed'

const { t } = useI18n()
const stage = ref<Stage>('loading')
const token = ref('')

function enter(account: Account): void {
	auth.account = account
	setLocale(account.language)
	stage.value = 'app'
}

function leaveToLogin(): void {
	auth.account = null
	stage.value = 'login'
}

function dropTokenFromUrl(): void {
	const url = new URL(location.href)
	url.searchParams.delete('set-password')
	history.replaceState(null, '', url.pathname + url.search + url.hash)
}

function onSignedIn(account: Account): void {
	if (token.value) {
		token.value = ''
		dropTokenFromUrl()
	}
	enter(account)
}

function toLogin(): void {
	token.value = ''
	dropTokenFromUrl()
	void start(false)
}

async function start(readToken = true): Promise<void> {
	stage.value = 'loading'
	try {
		auth.config = await api.authConfig()
	} catch {
		// an older server without the route is a Nextcloud install
		auth.config = null
		stage.value = 'app'
		return
	}
	if (auth.config.mode !== 'standalone') {
		stage.value = 'app'
		return
	}
	setUnauthorizedHandler(() => {
		if (stage.value === 'app') leaveToLogin()
	})
	if (readToken) {
		const found = new URLSearchParams(location.search).get('set-password')
		if (found) {
			token.value = found
			stage.value = 'set-password'
			return
		}
	}
	try {
		const me = await api.me()
		if (me.mode === 'standalone') enter(me)
		else stage.value = 'app'
	} catch (err) {
		stage.value = err instanceof ApiError && err.status === 401 ? 'login' : 'failed'
	}
}

onMounted(() => void start())
onBeforeUnmount(() => setUnauthorizedHandler(null))
</script>

<template>
	<template v-if="stage === 'app'">
		<App @signed-out="leaveToLogin" />
	</template>
	<SetPasswordView
		v-else-if="stage === 'set-password'"
		:token="token"
		@signed-in="onSignedIn"
		@to-login="toLogin" />
	<LoginView v-else-if="stage === 'login' && auth.config" :config="auth.config" @signed-in="onSignedIn" />
	<main v-else-if="stage === 'failed'" class="cz-card" style="max-width: 400px; margin: 10vh auto; padding: 24px">
		<p class="cz-error">{{ t('organizer.shell.auth.unreachable') }}</p>
		<CzButton @click="start()">{{ t('organizer.shell.auth.retry') }}</CzButton>
	</main>
</template>
