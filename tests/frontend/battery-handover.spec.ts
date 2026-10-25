// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * A dying phone asks for a backup while there is still time to add one.
 *
 * The rule is small and worth pinning: only the table's sole recorder asks
 * (a second phone IS the backup), an unknown battery never asks (Safari and
 * Firefox do not expose it), 15 % suggests a backup, 8 % shows the handover
 * code and says when to tap Finish. Nothing is automatic.
 */
import { describe, expect, it } from 'vitest'
import { batteryPrompt } from '../../frontend/src/recorder/batteryPrompt'
import BatteryHandover from '../../frontend/src/recorder/components/BatteryHandover.vue'
import TableBar from '../../frontend/src/recorder/components/TableBar.vue'
import { mountWithI18n } from './support/mount'

describe('batteryPrompt', () => {
	it('asks only the sole recorder of a table, and only when the battery is known', () => {
		expect(batteryPrompt(undefined, 1)).toBe('none')
		expect(batteryPrompt(0.9, 1)).toBe('none')
		expect(batteryPrompt(0.15, 1)).toBe('low')
		expect(batteryPrompt(0.08, 1)).toBe('critical')
		expect(batteryPrompt(0.03, 2)).toBe('none') // the other phone is the backup
		expect(batteryPrompt(0.03, undefined)).toBe('critical') // no table summary: treated as alone
	})
})

describe('the battery handover card', () => {
	it('suggests a backup phone at 15 %', async () => {
		const wrapper = mountWithI18n(BatteryHandover, { props: { prompt: 'low', level: 0.14 } })
		expect(wrapper.classes()).toContain('rc-note')
		expect(wrapper.text()).toContain('Battery at 14% — this is the only recorder at this table')
		expect(wrapper.find('button').text()).toBe('Add a backup phone')
		await wrapper.find('button').trigger('click')
		expect(wrapper.emitted('addBackup')).toHaveLength(1)
	})

	it('shows the handover instruction at 8 %', () => {
		const wrapper = mountWithI18n(BatteryHandover, { props: { prompt: 'critical', level: 0.07 } })
		expect(wrapper.classes()).toContain('rc-alert')
		expect(wrapper.text()).toContain('Battery at 7% — hand the table over')
		expect(wrapper.text()).toContain('When it shows RECORDING, tap Finish here.')
		expect(wrapper.find('button').text()).toBe('Show handover code')
	})
})

describe('the bar opens its sheet for a screen', () => {
	it('shows the Add recorder code when asked', async () => {
		const wrapper = mountWithI18n(TableBar, {
			props: {
				session: {
					session_token: 't',
					table_number: 3,
					table_color: 'orange',
					assembly: { id: 'a', name: 'A', language: 'en', recording_mode: 'independent' },
				},
			},
			global: { stubs: { CapabilityQr: { template: '<div class="qr-stub" />' } } },
		})
		expect(wrapper.find('.rc-sheet').exists()).toBe(false)
		;(wrapper.vm as unknown as { show: (p: string) => void }).show('ADD_RECORDER_TO_TABLE')
		await wrapper.vm.$nextTick()
		expect(wrapper.find('.rc-sheet .qr-stub').exists()).toBe(true)
	})
})
