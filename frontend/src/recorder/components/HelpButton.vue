<!--
	SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
	SPDX-License-Identifier: AGPL-3.0-or-later

	The table's hand. One quiet button on every table screen; a sheet asks
	what kind of help, one tap sends it, the line reads "Organizer notified"
	until the Live tab acknowledges it and then "The organizer has seen it".
	The parent passes what the status poll says about the table's hand; this
	keeps its own copy only between the tap and the next poll.
-->
<script setup lang="ts">
import { mdiHandBackLeft } from '@mdi/js'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import SvgIcon from '../../components/ui/SvgIcon.vue'
import { recorderApi, type HelpKind, type HelpState } from '../api'

const props = defineProps<{
	token: string
	/** from the status poll: null = no hand up, undefined = not known yet */
	help?: HelpState | null
}>()

const { t } = useI18n()
const open = ref(false)
const busy = ref(false)
const failed = ref(false)
const local = ref<HelpState | null>(null)
const dismissed = ref<string | null>(null)

// the server's word wins once it has one; null clears what the tap set
watch(
	() => props.help,
	(help) => {
		if (help !== undefined) local.value = help
	},
)

const shown = computed(() => {
	const state = props.help === undefined ? local.value : (props.help ?? local.value)
	return state && dismissed.value !== state.id + (state.acknowledged_at ?? '') ? state : null
})

const KINDS: HelpKind[] = ['TECHNICAL', 'ORGANIZER', 'PROCESS']

async function ask(kind: HelpKind): Promise<void> {
	busy.value = true
	failed.value = false
	try {
		local.value = await recorderApi.needHelp(props.token, kind)
		dismissed.value = null
		open.value = false
	} catch {
		failed.value = true
	} finally {
		busy.value = false
	}
}

function dismiss(): void {
	const state = shown.value
	if (state) dismissed.value = state.id + (state.acknowledged_at ?? '')
}
</script>

<template>
	<div class="rc-help">
		<p v-if="shown" class="rc-help__state" :class="{ 'rc-help__state--seen': shown.acknowledged_at }" role="status">
			<SvgIcon :path="mdiHandBackLeft" :size="16" />
			<span>{{ shown.acknowledged_at ? t('recorder.help.seen') : t('recorder.help.notified') }}</span>
			<button v-if="shown.acknowledged_at" type="button" class="rc-help__dismiss" :aria-label="t('recorder.help.dismiss')" @click="dismiss">×</button>
		</p>
		<button v-else type="button" class="rc-help__btn" @click="open = true">
			<SvgIcon :path="mdiHandBackLeft" :size="16" />
			{{ t('recorder.help.button') }}
		</button>

		<div v-if="open" class="rc-sheet-scrim" @click.self="open = false">
			<div class="rc-sheet" role="dialog" aria-modal="true">
				<p class="rc-eyebrow rc-center" style="display: block">{{ t('recorder.help.title') }}</p>
				<button
					v-for="kind in KINDS"
					:key="kind"
					type="button"
					class="rc-btn rc-primary"
					:disabled="busy"
					@click="ask(kind)">
					{{ t(`recorder.help.kind.${kind}`) }}
				</button>
				<p v-if="failed" class="rc-alert" style="margin: 10px 0 0">{{ t('recorder.help.failed') }}</p>
				<button type="button" class="rc-btn rc-subtle" @click="open = false">{{ t('recorder.help.cancel') }}</button>
			</div>
		</div>
	</div>
</template>

<style>
.rc-help { margin: -4px 16px 10px; }
.rc-help__btn {
	display: inline-flex;
	align-items: center;
	gap: 6px;
	background: none;
	border: 1px solid var(--rc-border);
	border-radius: 999px;
	color: var(--rc-muted);
	font-size: 0.8125rem;
	min-height: 36px;
	padding: 4px 12px;
	cursor: pointer;
}
.rc-help__state {
	display: inline-flex;
	align-items: center;
	gap: 6px;
	margin: 0;
	padding: 6px 12px;
	border-radius: 999px;
	background: #fff4e0;
	color: #8a5a00;
	font-size: 0.8125rem;
	font-weight: 600;
}
.rc-help__state--seen { background: #e6f4ea; color: #1e6b3a; }
.rc-help__dismiss {
	background: none;
	border: 0;
	color: inherit;
	font-size: 1.1rem;
	line-height: 1;
	padding: 0 2px;
	min-width: 32px;
	min-height: 28px;
	cursor: pointer;
}
</style>
