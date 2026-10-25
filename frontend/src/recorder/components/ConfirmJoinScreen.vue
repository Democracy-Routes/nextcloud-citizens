<!--
	SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
	SPDX-License-Identifier: AGPL-3.0-or-later

	A guard against an accident in a busy room, shown BEFORE a code is spent:
	a third recorder at a table that already has two, or a phone that was
	recording one table scanning a code for another. The server allows both;
	this only asks. Cancel never consumes the code.
-->
<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import TableBadge from './TableBadge.vue'

defineProps<{
	/** 'third-recorder' | 'switch-table' */
	kind: 'third-recorder' | 'switch-table'
	tableNumber: number
	colorKey?: string | null
	/** for 'third-recorder': how many phones the table already has */
	recorders?: number
	/** for 'switch-table': the table this phone was recording */
	previousTable?: number
}>()
const emit = defineEmits<{ join: []; cancel: [] }>()

const { t } = useI18n()
</script>

<template>
	<div class="rc-scroll">
		<div class="rc-hero" style="padding-top: 12vh">
			<TableBadge :number="tableNumber" :color-key="colorKey" hero />
			<h1 style="margin-top: 18px">
				{{
					kind === 'third-recorder'
						? t('recorder.guard.thirdRecorderTitle', { count: recorders ?? 0 })
						: t('recorder.guard.switchTableTitle', { from: previousTable ?? 0, to: tableNumber })
				}}
			</h1>
			<p class="rc-muted" style="margin-top: 12px">
				{{ kind === 'third-recorder' ? t('recorder.guard.thirdRecorderBody') : t('recorder.guard.switchTableBody') }}
			</p>
			<button class="rc-btn rc-primary" style="margin-top: 22px" @click="emit('join')">
				{{ t('recorder.guard.join', { number: tableNumber }) }}
			</button>
			<button class="rc-btn rc-subtle" @click="emit('cancel')">
				{{
					kind === 'switch-table'
						? t('recorder.guard.keepTable', { number: previousTable ?? 0 })
						: t('recorder.guard.cancel')
				}}
			</button>
		</div>
	</div>
</template>
