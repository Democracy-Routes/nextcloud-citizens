<!--
	SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
	SPDX-License-Identifier: AGPL-3.0-or-later

	The one bottom bar every table screen ends with: New table on the left, the
	screen's primary action in the middle (the slot), Add recorder on the right.
	Same positions on preflight, armed, recording and done, so people learn the
	layout once. A side button opens the intent-carrying QR (CapabilityQr) in a
	bottom sheet over the screen rather than pushing content around. Hidden in
	plenary, whose one shared code already adds phones to the one table; the
	primary action still renders there, alone.
-->
<script setup lang="ts">
import { mdiCellphoneSound, mdiTablePlus } from '@mdi/js'
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import SvgIcon from '../../components/ui/SvgIcon.vue'
import type { CapabilityPurpose, JoinResult } from '../api'
import CapabilityQr from './CapabilityQr.vue'

const props = defineProps<{
	session: JoinResult
	roundId?: string | null
	/** during recording: the side buttons stay available but step back */
	quiet?: boolean
}>()

const { t } = useI18n()
const open = ref<CapabilityPurpose | null>(null)
const plenary = props.session.assembly.recording_mode === 'plenary'
</script>

<template>
	<div class="rc-actions rc-bar" :class="{ 'rc-bar--plain': plenary, 'rc-bar--quiet': quiet }">
		<button
			v-if="!plenary"
			type="button"
			class="rc-bar__side"
			:class="{ 'rc-bar__side--open': open === 'ADD_TABLE' }"
			@click="open = 'ADD_TABLE'">
			<SvgIcon :path="mdiTablePlus" :size="22" />
			<span>{{ t('recorder.table.newTable') }}</span>
		</button>
		<div class="rc-bar__main"><slot /></div>
		<button
			v-if="!plenary"
			type="button"
			class="rc-bar__side"
			:class="{ 'rc-bar__side--open': open === 'ADD_RECORDER_TO_TABLE' }"
			@click="open = 'ADD_RECORDER_TO_TABLE'">
			<SvgIcon :path="mdiCellphoneSound" :size="22" />
			<span>{{ t('recorder.table.addRecorderShort') }}</span>
		</button>
	</div>

	<!-- the QR as a sheet over the screen; tapping the scrim or Close ends it -->
	<div v-if="open" class="rc-sheet-scrim" @click.self="open = null">
		<div class="rc-sheet" role="dialog" aria-modal="true">
			<CapabilityQr
				:key="open"
				:token="session.session_token"
				:purpose="open"
				:table-number="session.table_number"
				:color-key="session.table_color"
				:round-id="roundId"
				@close="open = null" />
		</div>
	</div>
</template>
