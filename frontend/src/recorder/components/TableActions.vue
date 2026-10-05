<!--
	SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
	SPDX-License-Identifier: AGPL-3.0-or-later

	The two things an authorized phone can add: a new table, or another recorder
	for this table. Either makes a code whose meaning is fixed before the next
	phone scans it (CapabilityQr). Side by side where there is room, stacked on
	a narrow phone. Not shown in plenary, whose one shared code already adds
	phones to the one table.
-->
<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { CapabilityPurpose, JoinResult } from '../api'
import CapabilityQr from './CapabilityQr.vue'

const props = defineProps<{ session: JoinResult; roundId?: string | null }>()

const { t } = useI18n()
const open = ref<CapabilityPurpose | null>(null)
const plenary = props.session.assembly.recording_mode === 'plenary'

function toggle(purpose: CapabilityPurpose): void {
	open.value = open.value === purpose ? null : purpose
}
</script>

<template>
	<div v-if="!plenary" class="rc-table-actions">
		<div class="rc-table-actions__row">
			<button class="rc-btn" :class="{ 'rc-primary': open === 'ADD_TABLE' }" @click="toggle('ADD_TABLE')">
				{{ t('recorder.table.addTable') }}
			</button>
			<button
				class="rc-btn"
				:class="{ 'rc-primary': open === 'ADD_RECORDER_TO_TABLE' }"
				@click="toggle('ADD_RECORDER_TO_TABLE')">
				{{ t('recorder.table.addRecorder') }}
			</button>
		</div>
		<CapabilityQr
			v-if="open"
			:key="open"
			:token="session.session_token"
			:purpose="open"
			:table-number="session.table_number"
			:color-key="session.table_color"
			:round-id="roundId"
			@close="open = null" />
	</div>
</template>
