<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
/** Who is signed in, the language of the interface, and Sign out. Standalone only. */
import { mdiLogout } from '@mdi/js'
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../../api'
import { auth } from '../../auth'
import { describeError } from '../../errors'
import { setLocale } from '../../i18n'
import { ASSEMBLY_LANGUAGES } from '../settings/useSettingsForm'
import CzButton from '../ui/CzButton.vue'

const emit = defineEmits<{ 'signed-out': [] }>()
const { t } = useI18n()
const error = ref('')

async function changeLanguage(event: Event): Promise<void> {
	const language = (event.target as HTMLSelectElement).value
	error.value = ''
	try {
		const account = await api.updateMe({ language })
		if (auth.account) auth.account.language = account.language
		setLocale(language)
	} catch (err) {
		error.value = describeError(err).message
	}
}

async function signOut(): Promise<void> {
	try {
		await api.logout()
	} catch {
		/* the cookie may already be gone; the login view is right either way */
	}
	emit('signed-out')
}
</script>

<template>
	<div v-if="auth.account" class="cz-account" data-test="account-menu" style="padding: 8px; display: grid; gap: 8px">
		<strong data-test="account-name">{{ auth.account.display_name || auth.account.username }}</strong>
		<label style="font-size: 0.8125rem">
			<span class="cz-muted">{{ t('organizer.shell.account.language') }}</span>
			<select :value="auth.account.language" data-test="account-language" style="width: 100%" @change="changeLanguage">
				<option v-for="lang in ASSEMBLY_LANGUAGES" :key="lang.code" :value="lang.code">{{ lang.label }}</option>
			</select>
		</label>
		<div v-if="error" class="cz-error">{{ error }}</div>
		<CzButton small :icon="mdiLogout" data-test="sign-out" @click="signOut">{{ t('organizer.shell.account.signOut') }}</CzButton>
	</div>
</template>
