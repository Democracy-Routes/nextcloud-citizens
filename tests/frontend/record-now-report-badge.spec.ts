// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/** The phone's report says so when no person reviewed it. */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ReportScreen from '../../frontend/src/recorder/components/ReportScreen.vue'
import { mountWithI18n } from './support/mount'

const report = vi.fn()

vi.mock('../../frontend/src/recorder/api', async () => {
	const actual = await vi.importActual<Record<string, unknown>>('../../frontend/src/recorder/api')
	return { ...actual, recorderApi: { report: (...a: unknown[]) => report(...a) } }
})

function published(extra: Record<string, unknown>) {
	return {
		assembly: { name: 'Bologna', description: '', language: 'en', participants: 0, expected_participants: 0, tables: 1 },
		method: '',
		methodology_note: '',
		published_at: null,
		rounds: [],
		...extra,
	}
}

async function mountReport() {
	const wrapper = mountWithI18n(ReportScreen, { props: { token: 'tok', assemblyName: 'Bologna', tableNumber: 1 } })
	await flushPromises()
	return wrapper
}

beforeEach(() => report.mockReset())

describe('report screen AI label', () => {
	it('shows the label when the report is auto generated', async () => {
		report.mockResolvedValue(published({ auto_generated: true }))
		const wrapper = await mountReport()
		expect(wrapper.get('[data-test="report-auto-generated"]').text()).toContain('not reviewed by a person')
	})

	it('shows nothing for a reviewed report', async () => {
		report.mockResolvedValue(published({ auto_generated: false }))
		const wrapper = await mountReport()
		expect(wrapper.find('[data-test="report-auto-generated"]').exists()).toBe(false)
	})
})
