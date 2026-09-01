<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import { computed, useAttrs, useSlots } from 'vue'
import SvgIcon from './SvgIcon.vue'

const props = withDefaults(
	defineProps<{
		variant?: 'primary' | 'secondary' | 'danger' | 'tertiary'
		icon?: string
		small?: boolean
		disabled?: boolean
		wide?: boolean
		/** Accessible name for an icon-only button.
		 *
		 * Icon-only buttons relied on `title`, which most screen readers do not
		 * announce and no touch device shows at all — so the delete, move and
		 * edit controls throughout the app had no name. Falls back to `title`
		 * where one is already set, so no call site is left worse off. */
		label?: string
	}>(),
	{ variant: 'secondary', icon: '', small: false, disabled: false, wide: false, label: '' },
)

const slots = useSlots()
const attrs = useAttrs()

/** Only when there is no visible text: a slot already names the button.
 *
 * Falls back to any `title` the call site already passes, so the dozens of
 * existing icon-only buttons become announceable without each one being
 * edited — and a `title` alone was never enough, since screen readers largely
 * ignore it and touch devices never show it. */
const accessibleName = computed(() => {
	if (slots.default) return undefined
	return props.label || (typeof attrs.title === 'string' ? attrs.title : undefined)
})
</script>

<template>
	<button
		class="cz-btn"
		:class="[`cz-btn--${variant}`, { 'cz-btn--small': small, 'cz-btn--wide': wide }]"
		:disabled="disabled"
		:aria-label="accessibleName"
		type="button">
		<SvgIcon v-if="icon" :path="icon" :size="small ? 16 : 18" />
		<span class="cz-btn__label"><slot /></span>
	</button>
</template>
