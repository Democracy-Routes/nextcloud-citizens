<!--
	SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
	SPDX-License-Identifier: AGPL-3.0-or-later

	What the code this phone scanned made it: another recorder of a table, or
	the first recorder of a table that was just created. The phone did not
	choose; this screen says what was decided and asks for one tap before the
	usual consent and set-up screens.
-->
<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Joined } from '../api'
import { slotLabel } from '../slots'
import TableBadge from './TableBadge.vue'

const props = defineProps<{ joined: Joined }>()
const emit = defineEmits<{ continue: [] }>()

const { t } = useI18n()
const label = computed(() => slotLabel(props.joined.slot))
</script>

<template>
	<div class="rc-scroll">
		<div class="rc-hero" style="padding-top: 12vh">
			<TableBadge :number="joined.table_number" :color-key="joined.color_key" hero />
			<h1 style="margin-top: 18px">
				{{
					joined.table_created
						? t('recorder.joined.newTable')
						: t('recorder.joined.asRecorder', { label })
				}}
			</h1>
			<p class="rc-muted" style="margin-top: 12px">{{ t('recorder.joined.body') }}</p>
			<button class="rc-btn rc-primary" style="margin-top: 22px" @click="emit('continue')">
				{{ t('recorder.joined.continue') }}
			</button>
		</div>
	</div>
</template>
