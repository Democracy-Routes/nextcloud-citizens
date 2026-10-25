// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The assembly wizard's retention group (0.7): default selected, with "keep
 * audio N days" and "zero retention" alongside it — the same choice the
 * Overview tab offers afterwards, made once at creation and sent straight
 * through to api.createAssembly.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AssemblyWizard from '../../frontend/src/components/AssemblyWizard.vue'
import { mountWithI18n } from './support/mount'

const createAssembly = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: { createAssembly: (...a: unknown[]) => createAssembly(...a) },
	ApiError: class extends Error {
		status = 0
	},
	BASE: '',
}))

beforeEach(() => {
	createAssembly.mockReset().mockResolvedValue({ id: 'a1', invites: [] })
})

// the retention group lives on step 1 (Basics), alongside tables and
// language — Continue moves past it, so it has to be set before advancing
async function wizardOnStep1() {
	const wrapper = mountWithI18n(AssemblyWizard)
	await wrapper.find('input[type="text"]').setValue('Bologna Mobility Assembly')
	return wrapper
}

async function continueAndSubmit(wrapper: ReturnType<typeof mountWithI18n>) {
	await wrapper.findAll('button').find((b) => b.text() === 'Continue')!.trigger('click')
	await wrapper.findAll('button').find((b) => b.text().includes('Create assembly'))!.trigger('click')
	await flushPromises()
}

describe('the assembly wizard retention choice', () => {
	it('defaults to the instance default, unselected audio_retention_days', async () => {
		const wrapper = await wizardOnStep1()
		await continueAndSubmit(wrapper)

		expect(createAssembly.mock.calls[0][0]).toMatchObject({
			audio_retention_days: null,
			zero_retention: false,
		})
	})

	it('sends the chosen number of days', async () => {
		const wrapper = await wizardOnStep1()
		const radios = wrapper.findAll('[data-test="retention"] input[type="radio"]')
		await radios[1].setValue() // "days"
		const daysInput = wrapper.find('[data-test="retention"] input[type="number"]')
		await daysInput.setValue(45)
		await continueAndSubmit(wrapper)

		expect(createAssembly.mock.calls[0][0]).toMatchObject({
			audio_retention_days: 45,
			zero_retention: false,
		})
	})

	it('sends zero retention and leaves audio_retention_days out of it', async () => {
		const wrapper = await wizardOnStep1()
		const radios = wrapper.findAll('[data-test="retention"] input[type="radio"]')
		await radios[2].setValue() // "zero"
		await continueAndSubmit(wrapper)

		const sent = createAssembly.mock.calls[0][0]
		expect(sent.zero_retention).toBe(true)
		expect(sent.audio_retention_days).toBeUndefined()
	})
})
