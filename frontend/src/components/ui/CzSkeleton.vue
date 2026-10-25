<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import { useI18n } from 'vue-i18n'

withDefaults(defineProps<{ rows?: number; height?: number }>(), { rows: 3, height: 48 })

const { t } = useI18n()
</script>

<template>
	<div class="cz-skeleton" aria-busy="true" :aria-label="t('organizer.settings.ui.loading')">
		<div
			v-for="row in rows"
			:key="row"
			class="cz-skeleton__row"
			:style="{ height: height + 'px' }"></div>
	</div>
</template>
