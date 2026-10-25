<!--
	SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
	SPDX-License-Identifier: AGPL-3.0-or-later

	A quiet card while recording, only when this phone is the table's sole
	recorder and its battery is going: at 15 % suggest a backup phone, at 8 %
	show the handover code and say when to tap Finish. The second phone joins
	as the table's next recorder and records beside this one; this one finishes
	normally and the live captions pass on by themselves. Nothing automatic.
-->
<script setup lang="ts">
import { mdiBatteryAlertVariantOutline } from '@mdi/js'
import { useI18n } from 'vue-i18n'
import SvgIcon from '../../components/ui/SvgIcon.vue'
import type { BatteryPrompt } from '../batteryPrompt'

defineProps<{
	prompt: Exclude<BatteryPrompt, 'none'>
	/** 0–1 */
	level: number
}>()
const emit = defineEmits<{ addBackup: [] }>()

const { t } = useI18n()
</script>

<template>
	<div :class="prompt === 'critical' ? 'rc-alert' : 'rc-note'" class="rc-battery" role="status">
		<div class="rc-battery__head">
			<SvgIcon :path="mdiBatteryAlertVariantOutline" :size="20" />
			<strong>
				{{
					prompt === 'critical'
						? t('recorder.battery.criticalTitle', { percent: Math.round(level * 100) })
						: t('recorder.battery.lowTitle', { percent: Math.round(level * 100) })
				}}
			</strong>
		</div>
		<p>{{ prompt === 'critical' ? t('recorder.battery.criticalBody') : t('recorder.battery.lowBody') }}</p>
		<button type="button" class="rc-btn rc-subtle rc-battery__btn" @click="emit('addBackup')">
			{{ prompt === 'critical' ? t('recorder.battery.showCode') : t('recorder.battery.addBackup') }}
		</button>
	</div>
</template>

<style>
.rc-battery { text-align: left; }
.rc-battery__head { display: flex; align-items: center; gap: 8px; }
.rc-battery p { margin: 6px 0 0; }
.rc-battery__btn { margin-top: 10px; }
</style>
