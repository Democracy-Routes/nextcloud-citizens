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
import { useI18n } from 'vue-i18n'
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

const { t } = useI18n()

const props = defineProps<{ assemblyId: string }>()
const emit = defineEmits<{ changed: [] }>()

const participants = ref<Participant[]>([])

/** The CSV import's header row: column names the server reads, not prose. */
const CSV_HEADER = 'label,name,email'

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
		toast(t('organizer.setup.participants.copyFailed'), 'error')
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
	const where = participant.registered_table_number
		? t('organizer.setup.participants.source.table', { number: participant.registered_table_number })
		: ''
	const how =
		participant.source === 'SELF_PHONE' ? t('organizer.setup.participants.source.ownPhone')
		: participant.source === 'TABLE_DEVICE' ? t('organizer.setup.participants.source.tablePhone')
		: participant.consent?.method === 'PAPER' ? t('organizer.setup.participants.source.paper')
		: ''
	return [where, how ? `(${how})` : ''].filter(Boolean).join(' ')
}

function consentTitle(participant: Participant): string {
	const consent = participant.consent
	if (!consent) return t('organizer.setup.participants.consentTitle.none')
	const answer = (given: boolean) =>
		t(given ? 'organizer.setup.participants.consentTitle.yes' : 'organizer.setup.participants.consentTitle.no')
	const ticks = [
		`${t('organizer.setup.participants.consentTitle.recording')} ${answer(consent.recording)}`,
		`${t('organizer.setup.participants.consentTitle.transcription')} ${answer(consent.transcription)}`,
		`${t('organizer.setup.participants.consentTitle.analysis')} ${answer(consent.analysis)}`,
		`${t('organizer.setup.participants.consentTitle.quotations')} ${answer(consent.publication)}`,
	]
	return t('organizer.setup.participants.consentTitle.summary', {
		ticks: ticks.join(', '),
		version: consent.notice_version,
		hash: consent.notice_hash.slice(0, 8),
		at: consent.confirmed_at,
	})
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
		toast(t('organizer.setup.participants.imported', { count: imported.length }, imported.length))
	})

function prefill(): void {
	const start = participants.value.length + 1
	csvText.value =
		`${CSV_HEADER}\n` +
		Array.from({ length: 50 }, (_, i) => `P${String(start + i).padStart(3, '0')},,`).join('\n')
	showCsv.value = true
}

const remove = () =>
	run(async () => {
		if (removeTarget.value) await api.deleteParticipant(removeTarget.value.id)
		removeTarget.value = null
	})

/** "P001 (Anna)" — the label, and the name when there is one. */
function describe(participant: Participant): string {
	return participant.name ? `${participant.label} (${participant.name})` : participant.label
}

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
					<input v-model="newLabel" type="text" :placeholder="t('organizer.setup.participants.labelPlaceholder')" style="width: 140px" @keyup.enter="addOne" />
					<input v-model="newName" type="text" :placeholder="t('organizer.setup.participants.namePlaceholder')" style="width: 200px" @keyup.enter="addOne" />
					<CzButton variant="primary" small :icon="mdiAccountPlus" :disabled="busy || !newLabel.trim()" @click="addOne">{{ t('organizer.setup.participants.add') }}</CzButton>
					<span style="flex: 1"></span>
					<CzButton small :icon="mdiFileDelimitedOutline" @click="showCsv = !showCsv">{{ t('organizer.setup.participants.csvImport') }}</CzButton>
					<CzButton small :icon="mdiPlaylistPlus" :disabled="busy" @click="prefill">{{ t('organizer.setup.participants.prefill') }}</CzButton>
					<!-- the register an auditor asks for: who accepted what, against
					     which notice, when, by which method -->
					<CzButton
						v-if="participants.some((p) => p.consent)"
						small
						:icon="mdiDownloadOutline"
						:title="t('organizer.setup.participants.registerTitle')"
						@click="exportRegister('csv')">
						{{ t('organizer.setup.participants.registerCsv') }}
					</CzButton>
					<CzButton v-if="participants.some((p) => p.consent)" small :icon="mdiDownloadOutline" @click="exportRegister('pdf')">
						{{ t('organizer.setup.participants.registerPdf') }}
					</CzButton>
				</div>
				<div v-if="showCsv" style="margin-top: 14px">
					<p class="cz-muted" style="font-size: 0.8125rem">
						{{ t('organizer.setup.participants.csvHintBefore') }} <code>{{ CSV_HEADER }}</code> {{ t('organizer.setup.participants.csvHintAfter') }}
					</p>
					<textarea v-model="csvText" rows="8" style="width: 100%; font-family: ui-monospace, monospace"></textarea>
					<div class="cz-row" style="margin-top: 8px; justify-content: flex-end">
						<CzButton variant="primary" small :disabled="busy || !csvText.trim()" @click="importCsv">{{ t('organizer.setup.participants.import') }}</CzButton>
					</div>
				</div>
			</div>

			<!-- pre-registration: one link for everyone, people register and
			     consent at home, the table phone seats them by name -->
			<div v-if="registration" class="cz-card" data-test="registration-link">
				<div class="cz-row" style="align-items: flex-start; gap: 16px">
					<div style="flex: 1">
						<h3 style="margin: 0 0 6px">{{ t('organizer.setup.participants.registration.title') }}</h3>
						<p class="cz-muted" style="font-size: 0.8125rem; margin: 0 0 10px">
							{{ t('organizer.setup.participants.registration.body') }}
							<template v-if="registration.registered.total">
								<strong>{{ t('organizer.setup.participants.registration.counts', { total: registration.registered.total, seated: registration.registered.seated }) }}</strong>
							</template>
						</p>
						<template v-if="registration.url">
							<code style="font-size: 0.75rem; word-break: break-all">{{ registration.url }}</code>
							<div class="cz-row" style="margin-top: 8px">
								<CzButton small :icon="mdiContentCopy" @click="copyRegistrationLink">
									{{ linkCopied ? t('organizer.setup.participants.registration.copied') : t('organizer.setup.participants.registration.copy') }}
								</CzButton>
							</div>
						</template>
						<CzButton v-else variant="primary" small :disabled="linkBusy" @click="makeRegistrationLink">
							{{ t('organizer.setup.participants.registration.create') }}
						</CzButton>
					</div>
					<CzQrImage v-if="registration.qr_svg" :svg="registration.qr_svg" :label="t('organizer.setup.participants.registration.qrLabel')" style="width: 120px" />
				</div>
			</div>

			<CzEmptyState
				v-if="participants.length === 0"
				:icon="mdiAccountGroup"
				:title="t('organizer.setup.participants.emptyTitle')"
				:hint="t('organizer.setup.participants.emptyHint')" />

			<template v-else>
				<h3 style="margin: 18px 0 10px">{{ t('organizer.setup.participants.count', { count: participants.length }, participants.length) }}</h3>
				<table class="cz-table">
					<thead>
						<tr>
							<th style="width: 40px"></th>
							<th>{{ t('organizer.setup.participants.columns.label') }}</th>
							<th>{{ t('organizer.setup.participants.columns.name') }}</th>
							<th>{{ t('organizer.setup.participants.columns.email') }}</th>
							<th>{{ t('organizer.setup.participants.columns.consent') }}</th>
							<th style="width: 60px"></th>
						</tr>
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
										{{ participant.consent.recording ? t('organizer.setup.participants.consented') : t('organizer.setup.participants.refused') }}
									</span>
									<span class="cz-muted"> · {{ sourceText(participant) }}</span>
								</template>
								<span v-else class="cz-muted">—</span>
							</td>
							<td style="text-align: right">
								<CzButton small variant="tertiary" :icon="mdiDeleteOutline" :title="t('organizer.setup.participants.remove')" :disabled="busy" @click="removeTarget = participant" />
							</td>
						</tr>
					</tbody>
				</table>
			</template>
		</template>

		<CzConfirm
			v-if="removeTarget"
			:title="t('organizer.setup.participants.removeTitle')"
			:message="t('organizer.setup.participants.removeMessage', { who: describe(removeTarget) })"
			:confirm-label="t('organizer.setup.participants.removeLabel')"
			tone="danger"
			@confirm="remove"
			@cancel="removeTarget = null" />
	</div>
</template>
