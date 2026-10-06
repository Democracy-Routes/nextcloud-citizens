<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import {
	mdiAccountGroup,
	mdiArrowRight,
	mdiDeleteOutline,
	mdiMonitorEye,
	mdiQrcode,
	mdiTableFurniture,
	mdiTimelineClockOutline,
} from '@mdi/js'
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../api'
import type { AssemblyDetail, ConsentMode, Invite } from '../types'
import CzButton from './ui/CzButton.vue'
import CzStatusPill from './ui/CzStatusPill.vue'
import SvgIcon from './ui/SvgIcon.vue'

const { t } = useI18n()

const props = defineProps<{ assembly: AssemblyDetail }>()
const emit = defineEmits<{
	navigate: [tab: 'rounds' | 'participants' | 'tables' | 'qr' | 'monitor']
	changed: []
	/** The parent owns the confirmation; this is only the trigger. */
	requestDelete: []
}>()

const invites = ref<Invite[]>([])

const editingDetails = ref(false)
const savingDetails = ref(false)
const detailsError = ref('')
const draft = ref<{
	name: string
	description: string
	language: string
	autoPurge: boolean
	redactNames: string
	participantConsent: ConsentMode
	aiFacilitator: 'default' | 'off' | 'light' | 'normal' | 'active'
}>({
	name: '', description: '', language: 'en', autoPurge: true, redactNames: '',
	participantConsent: 'optional', aiFacilitator: 'default',
})

/** The languages an assembly can be held in: the code is the API value, the
 * label is the language's own name and stays the same in every locale. */
const LANGUAGES = ['en', 'it', 'de', 'fr', 'es'] as const
const AI_LEVELS = ['default', 'off', 'light', 'normal', 'active'] as const

/** Has any table started recording?
 *
 * The language decides how audio is transcribed and which model is chosen for
 * it, so changing it once recording has begun would leave one assembly with
 * transcripts in two languages and no way to tell which is which. The per-round
 * recording count is already in this payload. */
const recordingHasBegun = computed(() =>
	props.assembly.rounds.some((round) => (round.recording_count ?? 0) > 0),
)

function startEditDetails(): void {
	draft.value = {
		name: props.assembly.name,
		description: props.assembly.description,
		language: props.assembly.language,
		autoPurge: props.assembly.auto_purge_device_audio,
		redactNames: props.assembly.redact_names,
		participantConsent: props.assembly.participant_consent ?? 'optional',
		aiFacilitator: (props.assembly.ai_facilitator ?? 'default') as 'default' | 'off' | 'light' | 'normal' | 'active',
	}
	detailsError.value = ''
	editingDetails.value = true
}

async function saveDetails(): Promise<void> {
	savingDetails.value = true
	detailsError.value = ''
	try {
		await api.updateAssembly(props.assembly.id, {
			name: draft.value.name.trim(),
			description: draft.value.description.trim(),
			auto_purge_device_audio: draft.value.autoPurge,
			redact_names: draft.value.redactNames.trim(),
			participant_consent: draft.value.participantConsent,
			ai_facilitator: draft.value.aiFacilitator,
			// never sent once recording has begun, so a stale form cannot
			// change it behind the guard
			...(recordingHasBegun.value ? {} : { language: draft.value.language }),
			// a language chosen by hand ends Record now's detection
			...(props.assembly.language_auto && draft.value.language !== props.assembly.language
				? { language_auto: false }
				: {}),
		})
		editingDetails.value = false
		emit('changed')
	} catch (err) {
		detailsError.value = err instanceof Error ? err.message : String(err)
	} finally {
		savingDetails.value = false
	}
}

const editingInstructions = ref(false)
const instructionsDraft = ref('')
const savingInstructions = ref(false)

function startEditInstructions(): void {
	instructionsDraft.value = props.assembly.analysis_instructions
	editingInstructions.value = true
}

async function saveInstructions(): Promise<void> {
	savingInstructions.value = true
	try {
		await api.updateAssembly(props.assembly.id, {
			analysis_instructions: instructionsDraft.value.trim(),
		})
		editingInstructions.value = false
		emit('changed')
	} finally {
		savingInstructions.value = false
	}
}

onMounted(async () => {
	try {
		invites.value = await api.listInvites(props.assembly.id)
	} catch {
		/* non-critical */
	}
})

const activeInvites = computed(() => invites.value.filter((i) => i.active).length)
const activeRound = computed(() => props.assembly.rounds.find((r) => r.status === 'ACTIVE'))
const doneRounds = computed(
	() => props.assembly.rounds.filter((r) => ['ENDED', 'PROCESSING', 'READY_FOR_REVIEW'].includes(r.status)).length,
)

interface NextStep {
	text: string
	action: string
	tab: 'rounds' | 'participants' | 'tables' | 'qr' | 'monitor'
}

// computed, not a constant: t() must re-run when the locale changes
const nextStep = computed<NextStep | null>(() => {
	if (activeRound.value) {
		return {
			text: t('organizer.setup.overview.next.liveText', { position: activeRound.value.position }),
			action: t('organizer.setup.overview.next.liveAction'),
			tab: 'monitor',
		}
	}
	if (props.assembly.rounds.length === 0) {
		return { text: t('organizer.setup.overview.next.roundsText'), action: t('organizer.setup.overview.next.roundsAction'), tab: 'rounds' }
	}
	if (props.assembly.participant_count === 0) {
		return { text: t('organizer.setup.overview.next.participantsText'), action: t('organizer.setup.overview.next.participantsAction'), tab: 'participants' }
	}
	if (activeInvites.value === 0) {
		return { text: t('organizer.setup.overview.next.qrText'), action: t('organizer.setup.overview.next.qrAction'), tab: 'qr' }
	}
	return { text: t('organizer.setup.overview.next.readyText'), action: t('organizer.setup.overview.next.liveAction'), tab: 'monitor' }
})
</script>

<template>
	<div>
		<div v-if="nextStep" class="cz-card" style="display: flex; align-items: center; gap: 14px; flex-wrap: wrap">
			<div style="flex: 1; min-width: 220px">
				<h3 style="margin-bottom: 3px">{{ t('organizer.setup.overview.nextStep') }}</h3>
				<p class="cz-muted" style="margin: 0">{{ nextStep.text }}</p>
			</div>
			<CzButton variant="primary" :icon="mdiArrowRight" @click="emit('navigate', nextStep.tab)">
				{{ nextStep.action }}
			</CzButton>
		</div>

		<div class="cz-statgrid">
			<button class="cz-stat cz-card--hover" style="background: none" @click="emit('navigate', 'participants')">
				<div class="cz-stat__icon"><SvgIcon :path="mdiAccountGroup" :size="24" /></div>
				<div>
					<div class="cz-stat__value">{{ assembly.participant_count }}<span class="cz-muted" style="font-size: 0.9375rem; font-weight: 500"> / {{ assembly.expected_participants }}</span></div>
					<div class="cz-stat__label">{{ t('organizer.setup.overview.stats.participants') }}</div>
				</div>
			</button>
			<button class="cz-stat cz-card--hover" style="background: none" @click="emit('navigate', 'tables')">
				<div class="cz-stat__icon"><SvgIcon :path="mdiTableFurniture" :size="24" /></div>
				<div>
					<div class="cz-stat__value">{{ assembly.default_table_count }}</div>
					<div class="cz-stat__label">{{ t('organizer.setup.overview.stats.tables') }}</div>
				</div>
			</button>
			<button class="cz-stat cz-card--hover" style="background: none" @click="emit('navigate', 'rounds')">
				<div class="cz-stat__icon"><SvgIcon :path="mdiTimelineClockOutline" :size="24" /></div>
				<div>
					<div class="cz-stat__value">{{ doneRounds }}<span class="cz-muted" style="font-size: 0.9375rem; font-weight: 500"> / {{ assembly.rounds.length }}</span></div>
					<div class="cz-stat__label">{{ t('organizer.setup.overview.stats.sessionsHeld') }}</div>
				</div>
			</button>
			<button class="cz-stat cz-card--hover" style="background: none" @click="emit('navigate', 'qr')">
				<div class="cz-stat__icon"><SvgIcon :path="mdiQrcode" :size="24" /></div>
				<div>
					<div class="cz-stat__value">{{ activeInvites }}</div>
					<div class="cz-stat__label">{{ t('organizer.setup.overview.stats.activeQr') }}</div>
				</div>
			</button>
		</div>

		<div class="cz-card">
			<div class="cz-row cz-row--spread" style="margin-bottom: 8px">
				<h3>{{ t('organizer.setup.overview.details.title') }}</h3>
				<CzButton v-if="!editingDetails" variant="tertiary" small @click="startEditDetails">
					{{ t('organizer.setup.overview.details.edit') }}
				</CzButton>
			</div>
			<template v-if="editingDetails">
				<div v-if="detailsError" class="cz-error">{{ detailsError }}</div>
				<div class="cz-field">
					<label for="cz-assembly-name">{{ t('organizer.setup.overview.details.name') }}</label>
					<input id="cz-assembly-name" v-model="draft.name" type="text" maxlength="200" />
				</div>
				<div class="cz-field">
					<label for="cz-assembly-description">{{ t('organizer.setup.overview.details.description') }}</label>
					<textarea id="cz-assembly-description" v-model="draft.description" rows="2"></textarea>
				</div>
				<div class="cz-field">
					<label for="cz-assembly-language">{{ t('organizer.setup.overview.details.language') }}</label>
					<select
						id="cz-assembly-language"
						v-model="draft.language"
						:disabled="recordingHasBegun">
						<option v-for="code in LANGUAGES" :key="code" :value="code">
							{{ t(`organizer.setup.overview.languages.${code}`) }}
						</option>
					</select>
					<span v-if="assembly.language_auto && !recordingHasBegun" class="cz-muted" style="font-size: 0.78rem">
						{{ t('organizer.setup.overview.details.languageDetected') }}
					</span>
					<span v-if="recordingHasBegun" class="cz-muted" style="font-size: 0.78rem">
						{{ t('organizer.setup.overview.details.languageLocked') }}
					</span>
				</div>
				<div class="cz-field">
					<label style="display: flex; align-items: center; gap: 8px; cursor: pointer">
						<input v-model="draft.autoPurge" type="checkbox" />
						{{ t('organizer.setup.overview.details.autoPurge') }}
					</label>
					<span class="cz-muted" style="font-size: 0.78rem">
						{{ t('organizer.setup.overview.details.autoPurgeHint') }}
					</span>
				</div>
				<div class="cz-field">
					<label>{{ t('organizer.setup.overview.details.consent') }}</label>
					<label style="display: flex; align-items: center; gap: 8px; cursor: pointer">
						<input v-model="draft.participantConsent" type="radio" value="required" />
						{{ t('organizer.setup.overview.details.consentRequired') }}
					</label>
					<label style="display: flex; align-items: center; gap: 8px; cursor: pointer">
						<input v-model="draft.participantConsent" type="radio" value="optional" />
						{{ t('organizer.setup.overview.details.consentOptional') }}
					</label>
					<span class="cz-muted" style="font-size: 0.78rem">
						{{ t('organizer.setup.overview.details.consentHint') }}
					</span>
				</div>
				<div class="cz-field" data-test="ai-facilitator">
					<label>{{ t('organizer.setup.overview.details.aiFacilitator') }}</label>
					<label v-for="level in AI_LEVELS" :key="level" style="display: flex; align-items: center; gap: 8px; cursor: pointer">
						<input v-model="draft.aiFacilitator" type="radio" :value="level" />
						{{ t(`organizer.setup.overview.details.aiLevel.${level}`, { level: assembly.ai_facilitator_default ?? 'off' }) }}
					</label>
					<span class="cz-muted" style="font-size: 0.78rem">
						{{ t('organizer.setup.overview.details.aiHint') }}
						<template v-if="assembly.ai_facilitator_configured === false">
							{{ t('organizer.setup.overview.details.aiNotConfigured') }}
						</template>
					</span>
				</div>
				<div class="cz-field">
					<label for="cz-redact-names">{{ t('organizer.setup.overview.details.redactNames') }}</label>
					<textarea
						id="cz-redact-names"
						v-model="draft.redactNames"
						rows="2"
						:placeholder="t('organizer.setup.overview.details.redactPlaceholder')"></textarea>
					<span class="cz-muted" style="font-size: 0.78rem">
						{{ t('organizer.setup.overview.details.redactHint') }}
					</span>
				</div>
				<div class="cz-row" style="justify-content: flex-end; margin-top: 8px">
					<CzButton variant="tertiary" small @click="editingDetails = false">{{ t('organizer.setup.overview.details.cancel') }}</CzButton>
					<CzButton
						variant="primary"
						small
						:disabled="savingDetails || !draft.name.trim()"
						@click="saveDetails">
						{{ t('organizer.setup.overview.details.save') }}
					</CzButton>
				</div>
			</template>
			<template v-else>
				<p v-if="assembly.description" style="margin: 0; font-size: 0.875rem; white-space: pre-wrap">
					{{ assembly.description }}
				</p>
				<p v-else class="cz-muted" style="margin: 0; font-size: 0.845rem">
					{{ t('organizer.setup.overview.details.noDescription') }}
				</p>
			</template>
		</div>

		<div class="cz-card">
			<div class="cz-row cz-row--spread" style="margin-bottom: 8px">
				<h3>{{ t('organizer.setup.overview.instructions.title') }}</h3>
				<CzButton v-if="!editingInstructions" variant="tertiary" small @click="startEditInstructions">
					{{ assembly.analysis_instructions ? t('organizer.setup.overview.details.edit') : t('organizer.setup.overview.details.add') }}
				</CzButton>
			</div>
			<template v-if="editingInstructions">
				<textarea
					v-model="instructionsDraft"
					rows="3"
					style="width: 100%"
					:placeholder="t('organizer.setup.overview.instructions.placeholder')"></textarea>
				<div class="cz-row" style="justify-content: flex-end; margin-top: 8px">
					<CzButton variant="tertiary" small @click="editingInstructions = false">{{ t('organizer.setup.overview.details.cancel') }}</CzButton>
					<CzButton variant="primary" small :disabled="savingInstructions" @click="saveInstructions">
						{{ t('organizer.setup.overview.details.save') }}
					</CzButton>
				</div>
			</template>
			<p v-else-if="assembly.analysis_instructions" style="margin: 0; font-size: 0.875rem; white-space: pre-wrap">
				{{ assembly.analysis_instructions }}
			</p>
			<p v-else class="cz-muted" style="margin: 0; font-size: 0.845rem">
				{{ t('organizer.setup.overview.instructions.empty') }}
			</p>
		</div>

		<div class="cz-card">
			<div class="cz-row cz-row--spread" style="margin-bottom: 8px">
				<h3>{{ t('organizer.setup.overview.sessions.title') }}</h3>
				<CzButton variant="tertiary" small :icon="mdiMonitorEye" @click="emit('navigate', 'monitor')">
					{{ t('organizer.setup.overview.sessions.liveView') }}
				</CzButton>
			</div>
			<p v-if="assembly.rounds.length === 0" class="cz-muted">{{ t('organizer.setup.overview.sessions.none') }}</p>
			<div
				v-for="round in assembly.rounds"
				:key="round.id"
				class="cz-row cz-row--spread"
				style="padding: 9px 0; border-bottom: 1px solid var(--cz-border)">
				<div class="cz-row" style="min-width: 0; flex-wrap: nowrap">
					<span class="cz-posbadge">{{ round.position }}</span>
					<div style="min-width: 0">
						<strong>{{ round.title || t('organizer.setup.overview.sessions.untitled') }}</strong>
						<p class="cz-muted" style="margin: 0; font-size: 0.8125rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">
							{{ round.question || t('organizer.setup.overview.sessions.noQuestion') }}
						</p>
					</div>
				</div>
				<div class="cz-row" style="flex-wrap: nowrap">
					<span class="cz-muted" style="font-size: 0.8125rem">{{ t('organizer.setup.overview.sessions.minutes', { minutes: round.duration_minutes }) }}</span>
					<CzStatusPill :status="round.status" />
				</div>
			</div>
		</div>

		<!-- Last, labelled, and away from everything else: this used to be a
		     small grey icon in the header, visually identical to Edit and Move
		     buttons elsewhere in the app. -->
		<div class="cz-card cz-dangerzone">
			<h3>{{ t('organizer.setup.overview.danger.title') }}</h3>
			<p class="cz-muted" style="margin: 6px 0 12px; font-size: 0.875rem">
				{{ t('organizer.setup.overview.danger.body') }}
			</p>
			<CzButton variant="danger" :icon="mdiDeleteOutline" @click="emit('requestDelete')">
				{{ t('organizer.setup.overview.danger.delete') }}
			</CzButton>
		</div>
	</div>
</template>

<style scoped>
.cz-dangerzone {
	border: 1px solid var(--color-error, #c62828);
}
</style>
