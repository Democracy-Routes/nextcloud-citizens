<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import { mdiContentCopy, mdiPlus, mdiPrinter, mdiQrcode, mdiRefresh, mdiCancel } from '@mdi/js'
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api, BASE } from '../api'
import { downloadFromApi } from '../download'
import { describeError, type UiError } from '../errors'
import type { AssemblyDetail, Invite, InviteGenerated } from '../types'
import CzButton from './ui/CzButton.vue'
import CzConfirm from './ui/CzConfirm.vue'
import CzEmptyState from './ui/CzEmptyState.vue'
import CzQrImage from './ui/CzQrImage.vue'
import CzError from './ui/CzError.vue'
import CzSkeleton from './ui/CzSkeleton.vue'
import { toast } from './ui/toast'

const props = defineProps<{ assembly: AssemblyDetail; initialGenerated?: InviteGenerated[] }>()

const { t } = useI18n()

// plenary is one shared code the whole room scans, not one code per table
const plenary = computed(() => props.assembly.recording_mode === 'plenary')
const emit = defineEmits<{ consumed: []; changed: [] }>()

const invites = ref<Invite[]>([])
// QR codes auto-generated at assembly creation arrive via initialGenerated
const generated = ref<InviteGenerated[]>(props.initialGenerated ?? [])
const error = ref('')
const busy = ref(false)
const confirmRevoke = ref(false)
// Regenerating invalidates every QR code already printed and taped to a table
// — strictly more disruptive than Revoke all, which always did ask.
const confirmRegenerate = ref(false)

const activeCount = () => invites.value.filter((i) => i.active).length
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
		toast(t('organizer.shell.qr.generated', { count: generated.value.length }))
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err)
	} finally {
		busy.value = false
	}
}

/** One more table, numbered next, in every round. The codes already on the
 * wall stay valid; only the new table has a code to print. */
async function addTable(): Promise<void> {
	busy.value = true
	error.value = ''
	try {
		const added = await api.addTable(props.assembly.id)
		generated.value = [...generated.value.filter((g) => g.table_number !== added.number), added.invite]
			.sort((a, b) => a.table_number - b.table_number)
		await reload()
		emit('changed')
		toast(t('organizer.shell.qr.tableAdded', { number: added.number }))
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
		toast(t('organizer.shell.qr.revoked'))
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err)
	} finally {
		busy.value = false
	}
}

const printing = ref<'' | 'sheet' | 'kit'>('')

/** The QR sheet (four codes per page, cut at the door) or the event kit (a
 * card per table with its colour, the programme, the recording notice —
 * printed the evening before). */
async function printSheet(kind: 'sheet' | 'kit' = 'sheet'): Promise<void> {
	// A real PDF, not window.print(): the browser print dropped every page
	// after the first, and the layout had to survive Nextcloud's global CSS.
	//
	// Fetched rather than window.open'd, because a popup blocker swallows the
	// new tab silently — and this is the single most time-critical action of
	// the event, taken at the door with people waiting.
	const path = kind === 'kit' ? 'event-kit.pdf' : 'invites/sheet.pdf'
	const url = `${BASE}/api/v1/assemblies/${props.assembly.id}/${path}`
	const name = `${props.assembly.name.slice(0, 40).replace(/ /g, '-')}-${kind === 'kit' ? 'event-kit' : 'qr-sheet'}.pdf`
	printing.value = kind
	try {
		await downloadFromApi(url, name)
	} catch {
		// last resort: let the browser try, and say so if that is blocked too
		if (!window.open(url, '_blank')) {
			toast(t('organizer.shell.qr.downloadFailed'), 'error')
		}
	} finally {
		printing.value = ''
	}
}

async function copyUrl(url: string): Promise<void> {
	try {
		await navigator.clipboard.writeText(url)
		toast(t('organizer.shell.qr.copied'))
	} catch {
		toast(t('organizer.shell.qr.copyFailed'), 'error')
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
					<h3>{{ plenary ? t('organizer.shell.qr.sharedCodeTitle') : t('organizer.shell.qr.tableCodesTitle') }}</h3>
					<p class="cz-muted" style="margin: 4px 0 0; font-size: 0.845rem">
						<template v-if="plenary">
							{{ t('organizer.shell.qr.sharedCodeHint') }}
						</template>
						<template v-else>
							{{ t('organizer.shell.qr.tableCodesHint') }}
						</template>
						<strong>{{ t('organizer.shell.qr.regenerateWarning') }}</strong>
					</p>
				</div>
				<div class="cz-row" style="flex-wrap: nowrap">
					<CzButton
						variant="primary"
						:icon="mdiRefresh"
						:disabled="busy"
						@click="hasActive() ? (confirmRegenerate = true) : generate()">
						{{ hasActive() ? t('organizer.shell.qr.regenerateAll') : t('organizer.shell.qr.generate') }}
					</CzButton>
					<CzButton v-if="generated.length" :icon="mdiPrinter" :disabled="!!printing" @click="printSheet('sheet')">
						{{ printing === 'sheet' ? t('organizer.shell.qr.preparing') : t('organizer.shell.qr.print') }}
					</CzButton>
					<CzButton
						v-if="generated.length"
						:icon="mdiPrinter"
						:disabled="!!printing"
						:title="t('organizer.shell.qr.printKitTitle')"
						@click="printSheet('kit')">
						{{ printing === 'kit' ? t('organizer.shell.qr.preparing') : t('organizer.shell.qr.printKit') }}
					</CzButton>
					<CzButton v-if="!plenary" :icon="mdiPlus" :disabled="busy" :title="t('organizer.shell.qr.addTableTitle')" @click="addTable">
						{{ t('organizer.shell.qr.addTable') }}
					</CzButton>
					<CzButton v-if="hasActive()" variant="tertiary" :icon="mdiCancel" :disabled="busy" @click="confirmRevoke = true">
						{{ t('organizer.shell.qr.revokeAll') }}
					</CzButton>
				</div>
			</div>
			<p
				v-if="generated.length && generated.length < activeCount()"
				class="cz-muted"
				style="margin: 12px 0 0; font-size: 0.8125rem">
				{{ t('organizer.shell.qr.partialSheet', { shown: generated.length, active: activeCount() }) }}
			</p>
			<p v-if="invites.length && !generated.length" class="cz-muted" style="margin: 12px 0 0; font-size: 0.8125rem">
				{{ t('organizer.shell.qr.staleCodes', { active: activeCount(), total: invites.length }) }}
			</p>
		</div>

		<!-- until the first load resolves, "No QR codes yet" is a guess — and
		     the one moment it is shown is while the facilitator is at the door -->
		<CzSkeleton v-if="!loaded && !loadError" :rows="3" :height="90" />

		<CzEmptyState
			v-else-if="!generated.length && !invites.length"
			:icon="mdiQrcode"
			:title="t('organizer.shell.qr.emptyTitle')"
			:hint="t('organizer.shell.qr.emptyHint')">
			<CzButton variant="primary" :icon="mdiRefresh" :disabled="busy" @click="generate">{{ t('organizer.shell.qr.generate') }}</CzButton>
		</CzEmptyState>

		<div v-if="generated.length" class="cz-qr-grid">
			<div v-for="invite in generated" :key="invite.table_number" class="cz-qr-item">
				<div class="cz-qr-item__assembly">{{ assembly.name }}</div>
				<h3>{{ t('organizer.shell.qr.tableBadge', { number: invite.table_number }) }}</h3>
				<CzQrImage :svg="invite.qr_svg" :label="t('organizer.shell.qr.qrAlt', { number: invite.table_number })" />
				<p style="font-size: 0.8125rem; margin: 0; color: #333">{{ t('organizer.shell.qr.scanHint') }}</p>
				<div class="cz-qr-url" :title="invite.url">{{ invite.url }}</div>
				<CzButton small :icon="mdiContentCopy" @click="copyUrl(invite.url)">
					{{ t('organizer.shell.qr.copyLink') }}
				</CzButton>
			</div>
		</div>

		<CzConfirm
			v-if="confirmRegenerate"
			:title="t('organizer.shell.qr.regenerateTitle')"
			:message="t('organizer.shell.qr.regenerateMessage', { count: activeCount() })"
			:confirm-label="t('organizer.shell.qr.regenerateConfirm')"
			tone="danger"
			@confirm="confirmRegenerate = false; generate()"
			@cancel="confirmRegenerate = false" />

		<CzConfirm
			v-if="confirmRevoke"
			:title="t('organizer.shell.qr.revokeTitle')"
			:message="t('organizer.shell.qr.revokeMessage')"
			:confirm-label="t('organizer.shell.qr.revokeConfirm')"
			tone="danger"
			@confirm="revoke"
			@cancel="confirmRevoke = false" />
	</div>
</template>
