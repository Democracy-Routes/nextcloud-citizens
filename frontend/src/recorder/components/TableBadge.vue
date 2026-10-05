<!--
	SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
	SPDX-License-Identifier: AGPL-3.0-or-later

	"TABLE 7 · BLUE": the number is the identity, the colour a cue for a room
	looking for the blue table. A server older than 0.7 sends no colour and the
	badge is simply "TABLE 7".
-->
<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps<{ number: number; colorKey?: string | null; hero?: boolean }>()

const { t, te } = useI18n()

const colorName = computed(() => {
	const key = props.colorKey ? `recorder.common.color.${props.colorKey}` : ''
	return key && te(key) ? t(key) : ''
})
</script>

<template>
	<span class="rc-table-badge" :class="{ 'rc-table-badge--hero': hero }">
		<span
			v-if="colorName"
			class="rc-tabledot"
			:class="`rc-tabledot--${colorKey}`"
			role="img"
			:aria-label="colorName"></span>
		<span>{{ t('recorder.common.tableBadge', { number }) }}<template v-if="colorName"> · {{ colorName }}</template></span>
	</span>
</template>
