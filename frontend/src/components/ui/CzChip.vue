<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
defineProps<{
	active: boolean
}>()

defineEmits<{
	click: []
}>()
</script>

<template>
	<!-- a real <button>, not a styled <span>: Enter/Space and focus already
	     work, and aria-pressed tells a screen reader this toggles rather than
	     navigates -->
	<button
		type="button"
		class="cz-chip"
		:class="{ 'cz-chip--active': active }"
		:aria-pressed="active"
		@click="$emit('click')">
		<slot />
	</button>
</template>
