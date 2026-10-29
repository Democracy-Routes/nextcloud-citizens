<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import {
	mdiArrowDown,
	mdiArrowUp,
	mdiCommentMultipleOutline,
	mdiDownloadOutline,
	mdiRefresh,
} from '@mdi/js'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api, ApiError, BASE } from '../api'
import { downloadFromApi } from '../download'
import type { AssemblyDetail, SeedsListing, StatementSeed } from '../types'
import CzButton from './ui/CzButton.vue'
import CzConfirm from './ui/CzConfirm.vue'
import CzEmptyState from './ui/CzEmptyState.vue'
import CzSkeleton from './ui/CzSkeleton.vue'
import CzStatusPill from './ui/CzStatusPill.vue'
import { toast } from './ui/toast'

const props = defineProps<{ assembly: AssemblyDetail }>()
const { t } = useI18n()

const listing = ref<SeedsListing | null>(null)
const error = ref('')
const busy = ref(false)
// per-row editing buffers: a seed id is present while its textarea is open
const drafts = ref<Record<string, string>>({})
const newText = ref('')
const adding = ref(false)
const confirmDeleteId = ref('')
const confirmRegenerate = ref(false)
const queuedLocally = ref(false)

const seeds = computed(() => listing.value?.seeds ?? [])
const maxChars = computed(() => listing.value?.max_chars ?? 400)
const softChars = computed(() => listing.value?.soft_chars ?? 140)
const jobLive = computed(() => {
	const state = listing.value?.job?.state
	return queuedLocally.value || state === 'QUEUED' || state === 'RUNNING' || state === 'RETRY'
})
const failed = computed(() => (listing.value?.job?.state === 'FAILED' ? listing.value.job : null))
const configured = computed(() => listing.value?.analysis_configured ?? false)
const noFindings = computed(() => (listing.value?.findings_approved ?? 0) === 0)
const canGenerate = computed(() => configured.value && !noFindings.value && !jobLive.value && !busy.value)

const counts = computed(() => ({
	approved: seeds.value.filter((s) => s.status === 'APPROVED' || s.status === 'EXPORTED').length,
	rejected: seeds.value.filter((s) => s.status === 'REJECTED').length,
	drafts: seeds.value.filter((s) => s.status === 'DRAFT').length,
}))

const REASON_KEYS = [
	'PROVIDER_AUTH', 'PROVIDER_RATE_LIMIT', 'PROVIDER_TIMEOUT', 'PROVIDER_HTTP',
	'SCHEMA_INVALID', 'NOT_CONFIGURED', 'NO_TRANSCRIPT', 'AUDIO_MISSING',
	'RERUN_EMPTY', 'CANCELLED', 'UNKNOWN',
]

const failureText = computed(() => {
	const job = failed.value
	if (!job) return ''
	const reason = job.failure_reason
	const text = reason
		? REASON_KEYS.includes(reason) ? t(`organizer.results.failure.reason.${reason}`) : reason
		: job.failure_detail || t('organizer.results.failure.reason.UNKNOWN')
	return t('organizer.results.seeds.failed', { reason: text })
})

/** The pill borrows the tones the status pill already has. */
const PILL_TONE: Record<StatementSeed['status'], string> = {
	DRAFT: 'DRAFT', APPROVED: 'COMPLETE', EXPORTED: 'COMPLETE', REJECTED: 'STALE',
}

function counterClass(text: string): string {
	const n = text.length
	if (n > maxChars.value) return 'cz-error'
	if (n > softChars.value) return 'cz-seed-warn'
	return 'cz-muted'
}

function message(err: unknown): string {
	return err instanceof Error ? err.message : String(err)
}

let timer = 0
function stopPolling(): void {
	window.clearTimeout(timer)
	timer = 0
}

async function load(): Promise<void> {
	try {
		listing.value = await api.listSeeds(props.assembly.id)
		error.value = ''
		const state = listing.value.job?.state
		if (state === 'QUEUED' || state === 'RUNNING' || state === 'RETRY') {
			schedulePoll()
		} else {
			queuedLocally.value = false
		}
	} catch (err) {
		error.value = message(err)
	}
}

function schedulePoll(): void {
	stopPolling()
	timer = window.setTimeout(() => void load(), 3000)
}

onMounted(load)
onBeforeUnmount(stopPolling)

async function generate(): Promise<void> {
	confirmRegenerate.value = false
	busy.value = true
	try {
		await api.generateSeeds(props.assembly.id)
		queuedLocally.value = true
		toast(t('organizer.results.seeds.toast.queued'))
		await load()
		// the job row may not exist yet; keep looking until it does and settles
		if (queuedLocally.value && !listing.value?.job) schedulePoll()
	} catch (err) {
		error.value = message(err)
	} finally {
		busy.value = false
	}
}

function onGenerate(): void {
	if (seeds.value.length) confirmRegenerate.value = true
	else void generate()
}

async function run(action: () => Promise<unknown>, done?: string): Promise<void> {
	busy.value = true
	try {
		await action()
		if (done) toast(done)
		await load()
	} catch (err) {
		error.value = message(err)
	} finally {
		busy.value = false
	}
}

function startEdit(seed: StatementSeed): void {
	if (!(seed.id in drafts.value)) drafts.value = { ...drafts.value, [seed.id]: seed.text }
}

function cancelEdit(id: string): void {
	const next = { ...drafts.value }
	delete next[id]
	drafts.value = next
}

function isDirty(seed: StatementSeed): boolean {
	return seed.id in drafts.value && drafts.value[seed.id] !== seed.text
}

function setDraft(id: string, value: string): void {
	drafts.value = { ...drafts.value, [id]: value }
}

async function saveEdit(seed: StatementSeed): Promise<void> {
	const text = (drafts.value[seed.id] ?? '').trim()
	if (!text || text.length > maxChars.value) return
	await run(() => api.updateSeed(props.assembly.id, seed.id, { text }), t('organizer.results.seeds.toast.saved'))
	cancelEdit(seed.id)
}

function setStatus(seed: StatementSeed, status: 'DRAFT' | 'APPROVED' | 'REJECTED'): Promise<void> {
	return run(() => api.updateSeed(props.assembly.id, seed.id, { status }))
}

async function removeSeed(): Promise<void> {
	const id = confirmDeleteId.value
	confirmDeleteId.value = ''
	await run(() => api.deleteSeed(props.assembly.id, id), t('organizer.results.seeds.toast.deleted'))
}

function move(index: number, delta: number): Promise<void> {
	const ids = seeds.value.map((s) => s.id)
	const target = index + delta
	if (target < 0 || target >= ids.length) return Promise.resolve()
	;[ids[index], ids[target]] = [ids[target], ids[index]]
	return run(() => api.reorderSeeds(props.assembly.id, ids))
}

const newTooLong = computed(() => newText.value.length > maxChars.value)

async function addSeed(): Promise<void> {
	const text = newText.value.trim()
	if (!text || newTooLong.value) return
	adding.value = true
	try {
		await api.createSeed(props.assembly.id, text)
		newText.value = ''
		toast(t('organizer.results.seeds.toast.saved'))
		await load()
	} catch (err) {
		error.value = message(err)
	} finally {
		adding.value = false
	}
}

async function download(extension: 'csv' | 'json'): Promise<void> {
	try {
		await downloadFromApi(`${BASE}/api/v1/assemblies/${props.assembly.id}/seeds/export.${extension}`)
	} catch (err) {
		// downloadFromApi throws a plain Error('HTTP 409'); ApiError only comes from api.ts
		const refused = (err instanceof ApiError && err.status === 409) || message(err).endsWith('409')
		if (refused) toast(t('organizer.results.seeds.toast.notReady'), 'error')
		else toast(t('organizer.results.seeds.toast.downloadFailed'), 'error')
	}
}
</script>

<template>
	<div>
		<div v-if="error" class="cz-error">{{ error }}</div>

		<div class="cz-card" style="margin-bottom: 16px">
			<div class="cz-row cz-row--spread">
				<div style="flex: 1; min-width: 240px">
					<h3>{{ t('organizer.results.seeds.title') }}</h3>
					<p class="cz-muted" style="margin: 4px 0 0; font-size: 0.845rem">{{ t('organizer.results.seeds.lead') }}</p>
				</div>
				<CzButton
					small
					variant="primary"
					:icon="mdiRefresh"
					:disabled="!canGenerate"
					data-test="seeds-generate"
					@click="onGenerate">
					{{ jobLive
						? t('organizer.results.seeds.queued')
						: seeds.length ? t('organizer.results.seeds.regenerate') : t('organizer.results.seeds.generate') }}
				</CzButton>
			</div>
			<p v-if="listing && !configured" class="cz-muted" style="margin: 8px 0 0; font-size: 0.8125rem" data-test="seeds-not-configured">
				{{ t('organizer.results.seeds.notConfigured') }}
			</p>
			<p v-else-if="listing && noFindings" class="cz-muted" style="margin: 8px 0 0; font-size: 0.8125rem" data-test="seeds-no-findings">
				{{ t('organizer.results.seeds.noFindings') }}
			</p>
			<p v-else-if="listing && seeds.length" class="cz-muted" style="margin: 8px 0 0; font-size: 0.8125rem">
				{{ t('organizer.results.seeds.generateHint') }}
			</p>
			<p v-if="failed" class="cz-error" role="alert" style="margin: 8px 0 0" data-test="seeds-failure">{{ failureText }}</p>
		</div>

		<CzSkeleton v-if="!listing && !error" :rows="4" />

		<template v-else-if="listing">
			<p v-if="seeds.length" class="cz-muted" style="margin: 0 0 10px; font-size: 0.875rem" data-test="seeds-summary">
				{{ t('organizer.results.seeds.summary', counts) }}
			</p>

			<CzEmptyState
				v-else
				:icon="mdiCommentMultipleOutline"
				:title="t('organizer.results.seeds.empty.title')"
				:hint="t('organizer.results.seeds.empty.hint')"
				data-test="seeds-empty" />

			<div v-for="(seed, index) in seeds" :key="seed.id" class="cz-card" style="margin-bottom: 10px" data-test="seed-row">
				<div class="cz-row" style="gap: 6px; margin-bottom: 8px">
					<CzStatusPill :status="PILL_TONE[seed.status]" :label="t(`organizer.results.seeds.status.${seed.status}`)" />
					<span class="cz-seed-badge">{{ t(`organizer.results.seeds.origin.${seed.origin}`) }}</span>
					<span v-if="seed.edited" class="cz-seed-badge">{{ t('organizer.results.seeds.edited') }}</span>
				</div>
				<textarea
					:value="drafts[seed.id] ?? seed.text"
					rows="2"
					style="width: 100%"
					:aria-label="t('organizer.results.seeds.title')"
					data-test="seed-text"
					@focus="startEdit(seed)"
					@input="setDraft(seed.id, ($event.target as HTMLTextAreaElement).value)" />
				<div class="cz-row cz-row--spread" style="margin-top: 4px">
					<span :class="counterClass(drafts[seed.id] ?? seed.text)" style="font-size: 0.8125rem" data-test="seed-counter">
						{{ t('organizer.results.seeds.chars', { count: (drafts[seed.id] ?? seed.text).length, max: maxChars }) }}
					</span>
					<span
						v-if="(drafts[seed.id] ?? seed.text).length > softChars"
						class="cz-muted"
						style="font-size: 0.8125rem">
						{{ t('organizer.results.seeds.tooLong', { soft: softChars, max: maxChars }) }}
					</span>
				</div>
				<p v-if="seed.stale" class="cz-seed-warn" style="margin: 6px 0 0; font-size: 0.8125rem">
					{{ t('organizer.results.seeds.stale') }}
				</p>
				<div class="cz-row" style="margin-top: 8px">
					<template v-if="seed.id in drafts">
						<CzButton
							small
							variant="primary"
							:disabled="busy || !isDirty(seed) || !(drafts[seed.id] ?? '').trim() || (drafts[seed.id] ?? '').length > maxChars"
							data-test="seed-save"
							@click="saveEdit(seed)">
							{{ t('organizer.results.seeds.save') }}
						</CzButton>
						<CzButton small variant="tertiary" data-test="seed-cancel" @click="cancelEdit(seed.id)">
							{{ t('organizer.results.seeds.cancel') }}
						</CzButton>
					</template>
					<template v-else>
						<CzButton
							v-if="seed.status !== 'APPROVED' && seed.status !== 'EXPORTED'"
							small
							variant="primary"
							:disabled="busy"
							data-test="seed-approve"
							@click="setStatus(seed, 'APPROVED')">
							{{ t('organizer.results.seeds.approve') }}
						</CzButton>
						<CzButton
							v-if="seed.status !== 'REJECTED'"
							small
							:disabled="busy"
							data-test="seed-reject"
							@click="setStatus(seed, 'REJECTED')">
							{{ t('organizer.results.seeds.reject') }}
						</CzButton>
						<CzButton
							v-if="seed.status !== 'DRAFT'"
							small
							variant="tertiary"
							:disabled="busy"
							data-test="seed-reopen"
							@click="setStatus(seed, 'DRAFT')">
							{{ t('organizer.results.seeds.reopen') }}
						</CzButton>
						<CzButton
							small
							variant="tertiary"
							:icon="mdiArrowUp"
							:disabled="busy || index === 0"
							:label="t('organizer.results.seeds.moveUp')"
							data-test="seed-up"
							@click="move(index, -1)" />
						<CzButton
							small
							variant="tertiary"
							:icon="mdiArrowDown"
							:disabled="busy || index === seeds.length - 1"
							:label="t('organizer.results.seeds.moveDown')"
							data-test="seed-down"
							@click="move(index, 1)" />
						<CzButton
							small
							variant="danger"
							:disabled="busy"
							data-test="seed-delete"
							@click="confirmDeleteId = seed.id">
							{{ t('organizer.results.seeds.delete') }}
						</CzButton>
					</template>
				</div>
			</div>

			<div class="cz-card" style="margin: 16px 0">
				<h3>{{ t('organizer.results.seeds.add') }}</h3>
				<textarea
					v-model="newText"
					rows="2"
					style="width: 100%; margin-top: 8px"
					:placeholder="t('organizer.results.seeds.addPlaceholder')"
					data-test="seed-add-text" />
				<div class="cz-row cz-row--spread" style="margin-top: 4px">
					<span :class="counterClass(newText)" style="font-size: 0.8125rem" data-test="seed-add-counter">
						{{ t('organizer.results.seeds.chars', { count: newText.length, max: maxChars }) }}
					</span>
					<span class="cz-row">
						<CzButton
							small
							variant="primary"
							:disabled="adding || !newText.trim() || newTooLong"
							data-test="seed-add-save"
							@click="addSeed">
							{{ t('organizer.results.seeds.save') }}
						</CzButton>
						<CzButton small variant="tertiary" :disabled="!newText" data-test="seed-add-cancel" @click="newText = ''">
							{{ t('organizer.results.seeds.cancel') }}
						</CzButton>
					</span>
				</div>
			</div>

			<div class="cz-card">
				<div class="cz-row cz-row--spread">
					<p class="cz-muted" style="flex: 1; min-width: 240px; margin: 0; font-size: 0.845rem">
						{{ t('organizer.results.seeds.exportHint') }}
					</p>
					<div class="cz-row">
						<CzButton
							small
							:icon="mdiDownloadOutline"
							:disabled="!listing.ready_to_export"
							data-test="seeds-export-csv"
							@click="download('csv')">
							{{ t('organizer.results.seeds.exportCsv') }}
						</CzButton>
						<CzButton
							small
							:icon="mdiDownloadOutline"
							:disabled="!listing.ready_to_export"
							data-test="seeds-export-json"
							@click="download('json')">
							{{ t('organizer.results.seeds.exportJson') }}
						</CzButton>
					</div>
				</div>
			</div>
		</template>

		<CzConfirm
			v-if="confirmDeleteId"
			:title="t('organizer.results.seeds.delete')"
			:message="t('organizer.results.seeds.confirmDelete')"
			:confirm-label="t('organizer.results.seeds.delete')"
			tone="danger"
			@confirm="removeSeed"
			@cancel="confirmDeleteId = ''" />
		<CzConfirm
			v-if="confirmRegenerate"
			:title="t('organizer.results.seeds.regenerate')"
			:message="t('organizer.results.seeds.confirmRegenerate')"
			:confirm-label="t('organizer.results.seeds.regenerate')"
			@confirm="generate"
			@cancel="confirmRegenerate = false" />
	</div>
</template>

<style>
.cz-seed-badge {
	font-size: 0.75rem;
	padding: 1px 8px;
	border-radius: 999px;
	border: 1px solid currentColor;
	opacity: 0.75;
}
.cz-seed-warn {
	color: var(--cz-amber, #b45309);
}
</style>
