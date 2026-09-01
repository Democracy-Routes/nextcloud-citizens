<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import { mdiContentCopy, mdiPrinter, mdiQrcode, mdiRefresh, mdiCancel } from '@mdi/js'
import { onMounted, ref } from 'vue'
import { api, BASE } from '../api'
import { describeError, type UiError } from '../errors'
import type { AssemblyDetail, Invite, InviteGenerated } from '../types'
import CzButton from './ui/CzButton.vue'
import CzConfirm from './ui/CzConfirm.vue'
import CzEmptyState from './ui/CzEmptyState.vue'
import CzError from './ui/CzError.vue'
import CzSkeleton from './ui/CzSkeleton.vue'
import { toast } from './ui/toast'

const props = defineProps<{ assembly: AssemblyDetail; initialGenerated?: InviteGenerated[] }>()
const emit = defineEmits<{ consumed: [] }>()

const invites = ref<Invite[]>([])
// QR codes auto-generated at assembly creation arrive via initialGenerated
const generated = ref<InviteGenerated[]>(props.initialGenerated ?? [])
const error = ref('')
const busy = ref(false)
const confirmRevoke = ref(false)
const loaded = ref(false)
const loadError = ref<UiError | null>(null)

async function reload(): Promise<void> {
	try {
		invites.value = await api.listInvites(props.assembly.id)
		loadError.value = null
	} catch (err) {
		// this tab is opened at the door, minutes before the event: an
		// unexplained empty list is the worst possible moment for one
		loadError.value = describeError(err)
		loaded.value = true
		return
	}
	loaded.value = true
	// tokens are stored encrypted server-side, so the sheet can always be
	// re-materialized (invites predating that storage come back empty)
	if (!generated.value.length && invites.value.some((i) => i.active)) {
		try {
			generated.value = await api.inviteLinks(props.assembly.id)
		} catch {
			/* older invites — the regenerate hint stays */
		}
	}
}

onMounted(() => {
	void reload()
	// local copy taken; the parent can clear its one-time handoff
	if (props.initialGenerated?.length) emit('consumed')
})

async function generate(): Promise<void> {
	busy.value = true
	error.value = ''
	try {
		generated.value = await api.generateInvites(props.assembly.id)
		await reload()
		toast(`${generated.value.length} QR codes generated`)
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err)
	} finally {
		busy.value = false
	}
}

async function revoke(): Promise<void> {
	confirmRevoke.value = false
	busy.value = true
	try {
		await api.revokeInvites(props.assembly.id)
		generated.value = []
		await reload()
		toast('All table codes revoked')
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err)
	} finally {
		busy.value = false
	}
}

function printSheet(): void {
	// A real PDF, not window.print(): the browser print dropped every page
	// after the first, and the layout had to survive Nextcloud's global CSS.
	window.open(`${BASE}/api/v1/assemblies/${props.assembly.id}/invites/sheet.pdf`, '_blank')
}

async function copyUrl(url: string): Promise<void> {
	try {
		await navigator.clipboard.writeText(url)
		toast('Link copied')
	} catch {
		toast('Could not copy — select the link text instead', 'error')
	}
}

const hasActive = () => invites.value.some((i) => i.active)
</script>

<template>
	<div>
		<CzError v-if="loadError" :error="loadError" @retry="reload" />
		<div v-else-if="error" class="cz-error">{{ error }}</div>

		<div class="cz-card">
			<div class="cz-row cz-row--spread">
				<div style="flex: 1; min-width: 240px">
					<h3>Table recorder QR codes</h3>
					<p class="cz-muted" style="margin: 4px 0 0; font-size: 13.5px">
						One code per physical table. Codes can be re-viewed and re-printed here
						anytime. <strong>Regenerating revokes all previous codes.</strong>
					</p>
				</div>
				<div class="cz-row" style="flex-wrap: nowrap">
					<CzButton variant="primary" :icon="mdiRefresh" :disabled="busy" @click="generate">
						{{ hasActive() ? 'Regenerate all' : 'Generate codes' }}
					</CzButton>
					<CzButton v-if="generated.length" :icon="mdiPrinter" @click="printSheet">Print</CzButton>
					<CzButton v-if="hasActive()" variant="tertiary" :icon="mdiCancel" :disabled="busy" @click="confirmRevoke = true">
						Revoke all
					</CzButton>
				</div>
			</div>
			<p
				v-if="generated.length && generated.length < invites.filter((i) => i.active).length"
				class="cz-muted"
				style="margin: 12px 0 0; font-size: 13px">
				Showing {{ generated.length }} of
				{{ invites.filter((i) => i.active).length }} table codes — the rest were issued
				under a different app secret and cannot be re-displayed. Regenerate to get a
				complete sheet, which revokes the current codes.
			</p>
			<p v-if="invites.length && !generated.length" class="cz-muted" style="margin: 12px 0 0; font-size: 13px">
				{{ invites.filter((i) => i.active).length }} of {{ invites.length }} table codes active,
				but they were issued before re-viewing existed — regenerate to obtain new QR codes.
			</p>
		</div>

		<!-- until the first load resolves, "No QR codes yet" is a guess — and
		     the one moment it is shown is while the facilitator is at the door -->
		<CzSkeleton v-if="!loaded && !loadError" :rows="3" :height="90" />

		<CzEmptyState
			v-else-if="!generated.length && !invites.length"
			:icon="mdiQrcode"
			title="No QR codes yet"
			hint="Generate one recording code per table, print the sheet, and place one code on each physical table.">
			<CzButton variant="primary" :icon="mdiRefresh" :disabled="busy" @click="generate">Generate codes</CzButton>
		</CzEmptyState>

		<div v-if="generated.length" class="cz-qr-grid">
			<div v-for="invite in generated" :key="invite.table_number" class="cz-qr-item">
				<div class="cz-qr-item__assembly">{{ assembly.name }}</div>
				<h3>TABLE {{ invite.table_number }}</h3>
				<div class="cz-qr-image" v-html="invite.qr_svg"></div>
				<p style="font-size: 13px; margin: 0; color: #333">Scan with the table recording phone</p>
				<div class="cz-qr-url" :title="invite.url">{{ invite.url }}</div>
				<CzButton small :icon="mdiContentCopy" @click="copyUrl(invite.url)">
					Copy link
				</CzButton>
			</div>
		</div>

		<CzConfirm
			v-if="confirmRevoke"
			title="Revoke all table codes?"
			message="Every printed or shared QR code stops working immediately. Phones already recording keep their session."
			confirm-label="Revoke all"
			@confirm="revoke"
			@cancel="confirmRevoke = false" />
	</div>
</template>
