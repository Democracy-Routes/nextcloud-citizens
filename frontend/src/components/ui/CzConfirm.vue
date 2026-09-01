<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
/**
 * Asking before doing something.
 *
 * `danger` defaulted to true and `confirmLabel` to "Delete", so every dialog
 * that forgot to say otherwise appeared as a red destructive warning. Two safe,
 * reversible actions — publishing the report to the table phones, and
 * re-transcribing from stored audio — looked exactly as alarming as deleting
 * every recording, while "Close session permanently" correctly passed
 * :danger="false" and looked mild. Colour therefore carried no information at
 * all, which is worse than having none.
 *
 * The default is now the safe one, `confirmLabel` is required, and there is a
 * third tone above `danger`: `destructive` makes the person type the name of
 * what they are about to destroy.
 */
import { mdiAlert, mdiHelpCircleOutline } from '@mdi/js'
import { computed, ref, useId } from 'vue'
import { useFocusTrap } from '../../composables/useFocusTrap'
import CzButton from './CzButton.vue'
import SvgIcon from './SvgIcon.vue'

const props = withDefaults(
	defineProps<{
		title: string
		message: string
		/** Required: "Delete" was a dangerous thing to default to. */
		confirmLabel: string
		tone?: 'default' | 'danger' | 'destructive'
		/** For `destructive`: the exact text the person must type to proceed. */
		confirmWord?: string
	}>(),
	{ tone: 'default' },
)
const emit = defineEmits<{ confirm: []; cancel: [] }>()

const dialog = ref<HTMLElement | null>(null)
const titleId = useId()
const messageId = useId()

// Cancel is focused first for anything destructive, so a reflex Enter on an
// unexpected dialog cannot confirm it
useFocusTrap(dialog, () => emit('cancel'), { initial: 'first' })

const typed = ref('')

const isDanger = computed(() => props.tone !== 'default')

const blocked = computed(
	() => !!props.confirmWord && typed.value.trim() !== props.confirmWord.trim(),
)
</script>

<template>
	<div class="cz-modal-mask" @click.self="emit('cancel')">
		<div
			ref="dialog"
			class="cz-modal"
			role="dialog"
			aria-modal="true"
			:aria-labelledby="titleId"
			:aria-describedby="messageId">
			<div class="cz-modal__head">
				<SvgIcon
					:path="isDanger ? mdiAlert : mdiHelpCircleOutline"
					:size="22"
					:class="isDanger ? 'cz-modal__icon--danger' : ''" />
				<h3 :id="titleId">{{ title }}</h3>
			</div>
			<p :id="messageId" class="cz-modal__message">{{ message }}</p>

			<label v-if="confirmWord" class="cz-modal__typeit">
				<span>{{ $t('confirm.typeToConfirm', { word: confirmWord }) }}</span>
				<input v-model="typed" type="text" autocomplete="off" />
			</label>

			<div class="cz-modal__actions">
				<CzButton variant="tertiary" @click="emit('cancel')">{{ $t('confirm.cancel') }}</CzButton>
				<CzButton
					:variant="isDanger ? 'danger' : 'primary'"
					:disabled="blocked"
					@click="emit('confirm')">
					{{ confirmLabel }}
				</CzButton>
			</div>
		</div>
	</div>
</template>

<style scoped>
.cz-modal__icon--danger {
	color: var(--color-error, #c62828);
}
.cz-modal__typeit {
	display: block;
	margin: 14px 0 4px;
	font-size: 0.875rem;
}
.cz-modal__typeit input {
	display: block;
	width: 100%;
	margin-top: 6px;
}
</style>
