<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
/** The accounts of a standalone installation: list, add, role, disable, invite, delete. */
import { mdiAccountMultipleOutline } from '@mdi/js'
import { onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../../api'
import { auth } from '../../auth'
import { describeError } from '../../errors'
import type { Account } from '../../types'
import CzButton from '../ui/CzButton.vue'
import CzConfirm from '../ui/CzConfirm.vue'
import { toast } from '../ui/toast'
import SettingsCard from './SettingsCard.vue'
import { ASSEMBLY_LANGUAGES } from './useSettingsForm'

const { t } = useI18n()

const users = ref<Account[]>([])
const mail = ref(false)
const loaded = ref(false)
const error = ref('')
const busy = ref(false)
const created = ref<{ username: string; invited: boolean } | null>(null)
const removing = ref<Account | null>(null)

const blank = () => ({
	username: '',
	display_name: '',
	email: '',
	role: 'organizer' as 'admin' | 'organizer',
	language: auth.account?.language ?? 'en',
})
const form = reactive(blank())

function fail(err: unknown): void {
	// 409 and 422 carry the server's own sentence, which describeError passes through
	error.value = describeError(err).message
}

async function load(): Promise<void> {
	try {
		const data = await api.listUsers()
		users.value = data.users
		mail.value = data.mail
		error.value = ''
	} catch (err) {
		fail(err)
	} finally {
		loaded.value = true
	}
}
onMounted(load)

async function run(action: () => Promise<unknown>): Promise<boolean> {
	if (busy.value) return false
	busy.value = true
	error.value = ''
	try {
		await action()
		return true
	} catch (err) {
		fail(err)
		return false
	} finally {
		busy.value = false
	}
}

async function add(): Promise<void> {
	created.value = null
	const ok = await run(async () => {
		const made = await api.createUser({
			username: form.username.trim(),
			display_name: form.display_name.trim(),
			email: form.email.trim() || null,
			role: form.role,
			language: form.language,
		})
		created.value = { username: made.username, invited: made.invited }
		Object.assign(form, blank())
	})
	if (ok) await load()
}

async function setRole(user: Account): Promise<void> {
	const role = user.role === 'admin' ? 'organizer' : 'admin'
	if (await run(() => api.updateUser(user.id, { role }))) await load()
}

async function toggleDisabled(user: Account): Promise<void> {
	if (await run(() => api.updateUser(user.id, { disabled: !user.disabled }))) await load()
}

async function sendAgain(user: Account): Promise<void> {
	const ok = await run(() => api.inviteUser(user.id))
	if (ok) toast(t('organizer.settings.users.linkSent', { name: user.username }))
}

async function confirmRemove(): Promise<void> {
	const user = removing.value
	removing.value = null
	if (user && (await run(() => api.deleteUser(user.id)))) await load()
}

function when(iso: string | null): string {
	return iso ? new Date(iso).toLocaleString() : t('organizer.settings.users.never')
}
</script>

<template>
	<SettingsCard
		:icon="mdiAccountMultipleOutline"
		:title="t('organizer.settings.users.title')"
		:lead="t('organizer.settings.users.lead')"
		:saveable="false"
		:error="error"
		test-id="card-users">
		<p v-if="loaded && !mail" class="cz-muted" data-test="users-no-mail">
			{{ t('organizer.settings.users.noMail') }}
		</p>
		<p v-if="!loaded && !error" class="cz-muted">{{ t('organizer.settings.about.loading') }}</p>

		<div v-if="users.length" style="overflow-x: auto">
			<table class="cz-table" data-test="users-table" style="width: 100%">
				<thead>
					<tr>
						<th>{{ t('organizer.settings.users.username') }}</th>
						<th>{{ t('organizer.settings.users.displayName') }}</th>
						<th>{{ t('organizer.settings.users.email') }}</th>
						<th>{{ t('organizer.settings.users.role') }}</th>
						<th>{{ t('organizer.settings.users.state') }}</th>
						<th>{{ t('organizer.settings.users.lastLogin') }}</th>
						<th></th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="user in users" :key="user.id" :data-test="`user-${user.username}`">
						<td>{{ user.username }}</td>
						<td>{{ user.display_name }}</td>
						<td>
							{{ user.email ?? '—' }}
							<span v-if="user.email && user.email_verified" class="cz-muted">
								({{ t('organizer.settings.users.verified') }})
							</span>
						</td>
						<td>{{ user.role === 'admin' ? t('organizer.settings.users.admin') : t('organizer.settings.users.organizer') }}</td>
						<td>
							{{
								user.disabled
									? t('organizer.settings.users.disabled')
									: user.has_password
										? t('organizer.settings.users.active')
										: t('organizer.settings.users.invited')
							}}
						</td>
						<td>{{ when(user.last_login_at) }}</td>
						<td style="white-space: nowrap">
							<CzButton small variant="tertiary" data-test="user-role" :disabled="busy" @click="setRole(user)">
								{{ user.role === 'admin' ? t('organizer.settings.users.makeOrganizer') : t('organizer.settings.users.makeAdmin') }}
							</CzButton>
							<CzButton small variant="tertiary" data-test="user-disable" :disabled="busy" @click="toggleDisabled(user)">
								{{ user.disabled ? t('organizer.settings.users.enable') : t('organizer.settings.users.disable') }}
							</CzButton>
							<CzButton
								v-if="user.email && !user.disabled"
								small
								variant="tertiary"
								data-test="user-invite"
								:disabled="busy"
								@click="sendAgain(user)">
								{{ t('organizer.settings.users.sendAgain') }}
							</CzButton>
							<CzButton small variant="tertiary" data-test="user-delete" :disabled="busy" @click="removing = user">
								{{ t('organizer.settings.users.delete') }}
							</CzButton>
						</td>
					</tr>
				</tbody>
			</table>
		</div>

		<form data-test="user-add-form" style="margin-top: 16px" @submit.prevent="add">
			<h4>{{ t('organizer.settings.users.addTitle') }}</h4>
			<div class="cz-field" style="max-width: 420px">
				<label>{{ t('organizer.settings.users.username') }}</label>
				<input v-model="form.username" type="text" data-test="add-username" autocomplete="off" required minlength="3" />
			</div>
			<div class="cz-field" style="max-width: 420px">
				<label>{{ t('organizer.settings.users.displayName') }}</label>
				<input v-model="form.display_name" type="text" data-test="add-display-name" />
			</div>
			<div class="cz-field" style="max-width: 420px">
				<label>{{ t('organizer.settings.users.email') }}</label>
				<input v-model="form.email" type="email" data-test="add-email" autocomplete="off" />
				<p class="cz-muted" style="font-size: 0.78rem; margin-top: 6px">{{ t('organizer.settings.users.emailHint') }}</p>
			</div>
			<div class="cz-row" style="gap: 16px">
				<div class="cz-field">
					<label>{{ t('organizer.settings.users.role') }}</label>
					<select v-model="form.role" data-test="add-role">
						<option value="organizer">{{ t('organizer.settings.users.organizer') }}</option>
						<option value="admin">{{ t('organizer.settings.users.admin') }}</option>
					</select>
				</div>
				<div class="cz-field">
					<label>{{ t('organizer.settings.users.language') }}</label>
					<select v-model="form.language" data-test="add-language">
						<option v-for="lang in ASSEMBLY_LANGUAGES" :key="lang.code" :value="lang.code">{{ lang.label }}</option>
					</select>
				</div>
			</div>
			<button
				type="submit"
				class="cz-btn cz-btn--primary"
				data-test="add-submit"
				:disabled="busy || form.username.trim().length < 3">
				{{ t('organizer.settings.users.add') }}
			</button>
			<p v-if="created" class="cz-muted" data-test="add-result" style="margin-top: 10px">
				{{ created.invited ? t('organizer.settings.users.invitationSent', { name: created.username }) : t('organizer.settings.users.noEmailResult', { name: created.username }) }}
			</p>
		</form>

		<CzConfirm
			v-if="removing"
			:title="t('organizer.settings.users.deleteTitle')"
			:message="t('organizer.settings.users.deleteMessage', { name: removing.username })"
			:confirm-label="t('organizer.settings.users.delete')"
			tone="danger"
			@confirm="confirmRemove"
			@cancel="removing = null" />
	</SettingsCard>
</template>
