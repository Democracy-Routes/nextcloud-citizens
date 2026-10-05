<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import {
	mdiAccountGroup,
	mdiAccountPlus,
	mdiContentCopy,
	mdiDeleteOutline,
	mdiDownloadOutline,
	mdiFileDelimitedOutline,
	mdiPlaylistPlus,
} from '@mdi/js'
import { onMounted, ref } from 'vue'
import { api, BASE } from '../api'
import { downloadFromApi } from '../download'
import { describeError, type UiError } from '../errors'
import { useAsyncAction } from '../composables/useAsyncAction'
import type { Participant, RegistrationLink } from '../types'
import CzButton from './ui/CzButton.vue'
import CzError from './ui/CzError.vue'
import CzConfirm from './ui/CzConfirm.vue'
import CzEmptyState from './ui/CzEmptyState.vue'
import CzQrImage from './ui/CzQrImage.vue'
import CzSkeleton from './ui/CzSkeleton.vue'
import { toast } from './ui/toast'

const props = defineProps<{ assemblyId: string }>()
const emit = defineEmits<{ changed: [] }>()

const participants = ref<Participant[]>([])

/* ---- pre-registration: one link, people register at home, seated at the
 * door by name on the table's phone ---- */
const registration = ref<RegistrationLink | null>(null)
const linkBusy = ref(false)
const linkCopied = ref(false)

async function loadRegistrationLink(): Promise<void> {
	try {
		registration.value = await api.registrationLink(props.assemblyId, false)
	} catch {
		/* an older server: the card simply does not appear */
	}
}

async function makeRegistrationLink(): Promise<void> {
	linkBusy.value = true
	try {
		registration.value = await api.registrationLink(props.assemblyId, true)
	} catch (err) {
		toast(describeError(err).message, 'error')
	} finally {
		linkBusy.value = false
	}
}

async function copyRegistrationLink(): Promise<void> {
	if (!registration.value?.url) return
	try {
		await navigator.clipboard.writeText(registration.value.url)
		linkCopied.value = true
		window.setTimeout(() => (linkCopied.value = false), 2500)
	} catch {
		toast('Copy failed — select the link and copy it by hand', 'error')
	}
}

async function exportRegister(kind: 'csv' | 'pdf'): Promise<void> {
	try {
		await downloadFromApi(`${BASE}/api/v1/assemblies/${props.assemblyId}/consent-register.${kind}`)
	} catch (err) {
		toast(describeError(err).message, 'error')
	}
}

/** Where a person registered: "Table 7 (table phone)" / "(own phone)". */
function sourceText(participant: Participant): string {
	const where = participant.registered_table_number ? `Table ${participant.registered_table_number}` : ''
	const how =
		participant.source === 'SELF_PHONE' ? 'own phone'
		: participant.source === 'TABLE_DEVICE' ? 'table phone'
		: participant.consent?.method === 'PAPER' ? 'paper'
		: ''
	return [where, how ? `(${how})` : ''].filter(Boolean).join(' ')
}

function consentTitle(participant: Participant): string {
	const consent = participant.consent
	if (!consent) return 'No consent recorded'
	const ticks = [
		`recording ${consent.recording ? 'yes' : 'no'}`,
		`transcription ${consent.transcription ? 'yes' : 'no'}`,
		`analysis ${consent.analysis ? 'yes' : 'no'}`,
		`quotations ${consent.publication ? 'yes' : 'no'}`,
	]
	return `${ticks.join(', ')} — notice ${consent.notice_version} (${consent.notice_hash.slice(0, 8)}), ${consent.confirmed_at}`
}
const loaded = ref(false)
const error = ref('')
const newLabel = ref('')
const newName = ref('')
const csvText = ref('')
const showCsv = ref(false)
const removeTarget = ref<Participant | null>(null)
const loadError = ref<UiError | null>(null)

async function reload(): Promise<void> {
	try {
		participants.value = await api.listParticipants(props.assemblyId)
		loadError.value = null
	} catch (err) {
		loadError.value = describeError(err)
	} finally {
		loaded.value = true
	}
}

onMounted(() => {
	void reload()
	void loadRegistrationLink()
})

const { busy, error: actionError, run: runGuarded } = useAsyncAction()

async function run(action: () => Promise<unknown>): Promise<void> {
	// pressing Enter twice used to add the participant twice, and a
	// double-clicked CSV import added fifty people twice
	if (await runGuarded(action)) {
		await reload()
		emit('changed')
	}
}

const addOne = () =>
	run(async () => {
		await api.addParticipants(props.assemblyId, [
			{ label: newLabel.value.trim(), name: newName.value.trim() },
		])
		newLabel.value = ''
		newName.value = ''
	})

const importCsv = () =>
	run(async () => {
		const imported = await api.importCsv(props.assemblyId, csvText.value)
		csvText.value = ''
		showCsv.value = false
		toast(`${imported.length} participants imported`)
	})

function prefill(): void {
	const start = participants.value.length + 1
	csvText.value =
		'label,name,email\n' +
		Array.from({ length: 50 }, (_, i) => `P${String(start + i).padStart(3, '0')},,`).join('\n')
	showCsv.value = true
}

const remove = () =>
	run(async () => {
		if (removeTarget.value) await api.deleteParticipant(removeTarget.value.id)
		removeTarget.value = null
	})

function initials(participant: Participant): string {
	if (participant.name) {
		return participant.name
			.split(/\s+/)
			.slice(0, 2)
			.map((part) => part[0]?.toUpperCase() ?? '')
			.join('')
	}
	return participant.label.slice(0, 3)
}
</script>

<template>
	<div>
		<CzError v-if="loadError" :error="loadError" @retry="reload" />
		<CzError v-else-if="actionError" :error="actionError" />
		<div v-else-if="error" class="cz-error">{{ error }}</div>
		<CzSkeleton v-if="!loaded" :rows="4" />

		<template v-else>
			<div class="cz-card">
				<div class="cz-row">
					<input v-model="newLabel" type="text" placeholder="Label (e.g. P001)" style="width: 140px" @keyup.enter="addOne" />
					<input v-model="newName" type="text" placeholder="Name (optional)" style="width: 200px" @keyup.enter="addOne" />
					<CzButton variant="primary" small :icon="mdiAccountPlus" :disabled="busy || !newLabel.trim()" @click="addOne">Add</CzButton>
					<span style="flex: 1"></span>
					<CzButton small :icon="mdiFileDelimitedOutline" @click="showCsv = !showCsv">CSV import</CzButton>
					<CzButton small :icon="mdiPlaylistPlus" :disabled="busy" @click="prefill">Prefill 50 anonymous</CzButton>
					<!-- the register an auditor asks for: who accepted what, against
					     which notice, when, by which method -->
					<CzButton
						v-if="participants.some((p) => p.consent)"
						small
						:icon="mdiDownloadOutline"
						title="Consent register — one row per recorded consent, with the notice texts"
						@click="exportRegister('csv')">
						Consent register (CSV)
					</CzButton>
					<CzButton v-if="participants.some((p) => p.consent)" small :icon="mdiDownloadOutline" @click="exportRegister('pdf')">
						PDF
					</CzButton>
				</div>
				<div v-if="showCsv" style="margin-top: 14px">
					<p class="cz-muted" style="font-size: 0.8125rem">
						Header <code>label,name,email</code> — names and emails are optional. Anonymous labels are enough.
					</p>
					<textarea v-model="csvText" rows="8" style="width: 100%; font-family: ui-monospace, monospace"></textarea>
					<div class="cz-row" style="margin-top: 8px; justify-content: flex-end">
						<CzButton variant="primary" small :disabled="busy || !csvText.trim()" @click="importCsv">Import participants</CzButton>
					</div>
				</div>
			</div>

			<!-- pre-registration: one link for everyone, people register and
			     consent at home, the table phone seats them by name -->
			<div v-if="registration" class="cz-card" data-test="registration-link">
				<div class="cz-row" style="align-items: flex-start; gap: 16px">
					<div style="flex: 1">
						<h3 style="margin: 0 0 6px">Pre-registration link</h3>
						<p class="cz-muted" style="font-size: 0.8125rem; margin: 0 0 10px">
							Send this before the event: people read the notice and register at home.
							At the door, "Find your name" on any table's phone seats them. One link for
							the whole assembly, valid 30 days, revoked with the table codes.
							<template v-if="registration.registered.total">
								<strong>{{ registration.registered.total }} registered ahead · {{ registration.registered.seated }} seated.</strong>
							</template>
						</p>
						<template v-if="registration.url">
							<code style="font-size: 0.75rem; word-break: break-all">{{ registration.url }}</code>
							<div class="cz-row" style="margin-top: 8px">
								<CzButton small :icon="mdiContentCopy" @click="copyRegistrationLink">
									{{ linkCopied ? 'Link copied' : 'Copy link' }}
								</CzButton>
							</div>
						</template>
						<CzButton v-else variant="primary" small :disabled="linkBusy" @click="makeRegistrationLink">
							Create the link
						</CzButton>
					</div>
					<CzQrImage v-if="registration.qr_svg" :svg="registration.qr_svg" label="Pre-registration QR code" style="width: 120px" />
				</div>
			</div>

			<CzEmptyState
				v-if="participants.length === 0"
				:icon="mdiAccountGroup"
				title="No participants yet"
				hint="Participants can stay fully anonymous — use “Prefill 50 anonymous” to generate P001…P050 in one click." />

			<template v-else>
				<h3 style="margin: 18px 0 10px">{{ participants.length }} participants</h3>
				<table class="cz-table">
					<thead>
						<tr><th style="width: 40px"></th><th>Label</th><th>Name</th><th>Email</th><th>Consent</th><th style="width: 60px"></th></tr>
					</thead>
					<tbody>
						<tr v-for="participant in participants" :key="participant.id">
							<td><span class="cz-avatar">{{ initials(participant) }}</span></td>
							<td><strong>{{ participant.label }}</strong></td>
							<td>{{ participant.name || '—' }}</td>
							<td class="cz-muted">{{ participant.email || '—' }}</td>
							<!-- the consent act recorded at the table (0.7): who registered
							     where and by which method, and whether they consented -->
							<td class="cz-consent" :title="consentTitle(participant)">
								<template v-if="participant.consent">
									<span :class="participant.consent.recording ? 'cz-consent--yes' : 'cz-consent--no'">
										{{ participant.consent.recording ? '✓ consented' : '✗ refused' }}
									</span>
									<span class="cz-muted"> · {{ sourceText(participant) }}</span>
								</template>
								<span v-else class="cz-muted">—</span>
							</td>
							<td style="text-align: right">
								<CzButton small variant="tertiary" :icon="mdiDeleteOutline" title="Remove" :disabled="busy" @click="removeTarget = participant" />
							</td>
						</tr>
					</tbody>
				</table>
			</template>
		</template>

		<CzConfirm
			v-if="removeTarget"
			title="Remove participant?"
			:message="`${removeTarget.label}${removeTarget.name ? ' (' + removeTarget.name + ')' : ''} will be removed from this assembly.`"
			confirm-label="Remove"
			tone="danger"
			@confirm="remove"
			@cancel="removeTarget = null" />
	</div>
</template>
