<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
/**
 * A tab list that behaves the way its ARIA roles claim.
 *
 * role="tablist" and role="tab" were declared without any of what they
 * promise: no aria-controls pointing at a panel, every tab in the tab order
 * rather than one, and arrow keys doing nothing. A screen reader announced
 * "tab" and then could not tell the user which panel it governed, while
 * keyboard users had to Tab through every tab to reach the content.
 */
import { computed } from 'vue'
import SvgIcon from './SvgIcon.vue'
import { panelId, tabId, type TabItem } from './tabs'

const props = defineProps<{ tabs: TabItem[]; modelValue: string; idPrefix: string }>()
const emit = defineEmits<{ 'update:modelValue': [id: string] }>()

const index = computed(() => props.tabs.findIndex((tab) => tab.id === props.modelValue))

function move(delta: number): void {
	const count = props.tabs.length
	if (count === 0) return
	const next = (index.value + delta + count) % count
	select(props.tabs[next].id)
}

function select(id: string): void {
	emit('update:modelValue', id)
	// roving tabindex: focus follows selection, so the new tab is where the
	// keyboard is
	requestAnimationFrame(() => {
		document.getElementById(tabId(props.idPrefix, id))?.focus()
	})
}

function onKeydown(event: KeyboardEvent): void {
	switch (event.key) {
		case 'ArrowRight':
			event.preventDefault()
			move(1)
			break
		case 'ArrowLeft':
			event.preventDefault()
			move(-1)
			break
		case 'Home':
			event.preventDefault()
			select(props.tabs[0].id)
			break
		case 'End':
			event.preventDefault()
			select(props.tabs[props.tabs.length - 1].id)
			break
	}
}
</script>

<template>
	<div class="cz-tabs" role="tablist" @keydown="onKeydown">
		<button
			v-for="item in tabs"
			:key="item.id"
			:id="tabId(idPrefix, item.id)"
			class="cz-tab"
			:class="{ 'cz-tab--active': modelValue === item.id }"
			role="tab"
			type="button"
			:aria-selected="modelValue === item.id"
			:aria-controls="panelId(idPrefix, item.id)"
			:tabindex="modelValue === item.id ? 0 : -1"
			@click="select(item.id)">
			<SvgIcon v-if="item.icon" :path="item.icon" :size="17" />
			{{ item.label }}
		</button>
	</div>
</template>
