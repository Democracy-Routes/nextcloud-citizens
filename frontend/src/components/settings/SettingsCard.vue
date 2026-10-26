<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
/**
 * One concern of the Settings page: icon, title, one-line lead, and its own
 * Save that lights up only when something in THIS card changed.
 */
import { useI18n } from 'vue-i18n'
import CzButton from '../ui/CzButton.vue'
import SvgIcon from '../ui/SvgIcon.vue'

withDefaults(
	defineProps<{
		icon: string
		title: string
		lead?: string
		/** false for cards whose actions apply immediately (models, About) */
		saveable?: boolean
		dirty?: boolean
		busy?: boolean
		error?: string
		/** a hook for specs and for the tests of other cards */
		testId?: string
	}>(),
	{ lead: '', saveable: true, dirty: false, busy: false, error: '', testId: '' },
)
const emit = defineEmits<{ save: [] }>()
const { t } = useI18n()
</script>

<template>
	<section class="cz-card cz-settings-card" :data-test="testId || undefined">
		<div class="cz-settings-card__head">
			<SvgIcon :path="icon" :size="22" style="color: var(--cz-primary)" />
			<div class="cz-settings-card__titles">
				<h3>{{ title }}</h3>
				<p v-if="lead" class="cz-muted">{{ lead }}</p>
			</div>
			<CzButton
				v-if="saveable"
				variant="primary"
				small
				data-test="card-save"
				:disabled="busy || !dirty"
				@click="emit('save')">
				{{ busy ? t('organizer.settings.card.saving') : dirty ? t('organizer.settings.card.save') : t('organizer.settings.card.saved') }}
			</CzButton>
		</div>
		<div v-if="error" class="cz-error" data-test="card-error">{{ error }}</div>
		<slot />
	</section>
</template>
