// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * S8 "change the language after recording began" and the audio-retention
 * choice, both on the Overview tab (0.7).
 *
 * Once a table has recorded, the language select is enabled again but a
 * change no longer rides the general Save — the old PUT still refuses
 * `language` once audio exists — so it is confirmed on its own and sent
 * through the dedicated route. Retention is a plain radio group that rides
 * the ordinary Save, except once zero retention has actually run: then it
 * is shown, not offered.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import OverviewTab from '../../frontend/src/components/OverviewTab.vue'
import { toasts } from '../../frontend/src/components/ui/toast'
import { mountWithI18n } from './support/mount'

const updateAssembly = vi.fn()
const changeLanguage = vi.fn()
const listInvites = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: {
		updateAssembly: (...a: unknown[]) => updateAssembly(...a),
		changeLanguage: (...a: unknown[]) => changeLanguage(...a),
		listInvites: (...a: unknown[]) => listInvites(...a),
	},
	ApiError: class extends Error {
		status = 0
	},
	BASE: '',
}))

const ASSEMBLY = {
	id: 'a1',
	kind: 'assembly',
	name: 'Bologna',
	description: '',
	language: 'en',
	language_auto: false,
	scheduled_at: null,
	status: 'ACTIVE',
	recording_mode: 'orchestrated',
	expected_participants: 40,
	participant_count: 10,
	default_table_count: 5,
	analysis_instructions: '',
	auto_purge_device_audio: true,
	redact_names: '',
	audio_retention_days: null,
	zero_retention: false,
	zero_retention_done_at: null,
	closed_at: null,
	created_by: 'u',
	created_at: 'now',
	// recording_count > 0 is recordingHasBegun's own signal
	rounds: [
		{ id: 'r1', position: 1, title: 'Round 1', question: 'Q', duration_minutes: 20, status: 'ENDED', started_at: null, ended_at: null, recording_count: 1 },
	],
}

beforeEach(() => {
	updateAssembly.mockReset()
	changeLanguage.mockReset()
	listInvites.mockReset().mockResolvedValue([])
})

async function mountOverview(assembly: Record<string, unknown> = ASSEMBLY) {
	const wrapper = mountWithI18n(OverviewTab, { props: { assembly } })
	await flushPromises()
	return wrapper
}

function clickButton(wrapper: ReturnType<typeof mountWithI18n>, text: string) {
	return wrapper.findAll('button').find((b) => b.text() === text)!.trigger('click')
}

describe('changing the language once recording has begun', () => {
	it('enables the select again, but puts it back until a change is confirmed', async () => {
		const wrapper = await mountOverview()
		await clickButton(wrapper, 'Edit')

		const select = wrapper.find('#cz-assembly-language')
		expect((select.element as HTMLSelectElement).disabled).toBe(false)

		await select.setValue('it')
		await flushPromises()

		expect((select.element as HTMLSelectElement).value).toBe('en')
		expect(wrapper.find('.cz-modal').exists()).toBe(true)
		expect(wrapper.find('.cz-modal').text()).toContain('Italiano')
	})

	it('commits the change on confirm and says how many recordings were queued', async () => {
		changeLanguage.mockResolvedValue({ language: 'it', queued: 3, skipped_no_audio: 0, closed: false })
		const wrapper = await mountOverview()
		await clickButton(wrapper, 'Edit')
		await wrapper.find('#cz-assembly-language').setValue('it')
		await clickButton(wrapper, 'Continue')
		await flushPromises()

		expect(changeLanguage).toHaveBeenCalledWith('a1', 'it')
		expect(wrapper.emitted('changed')).toBeTruthy()
		expect((wrapper.find('#cz-assembly-language').element as HTMLSelectElement).value).toBe('it')
		// toasts render in a container outside this isolated mount — check the
		// shared reactive list the toast() call actually pushed to
		expect(toasts.at(-1)?.text).toBe('3 recordings queued for transcription in Italiano')
	})

	it('never sends language through the general Save while recording', async () => {
		const wrapper = await mountOverview()
		await clickButton(wrapper, 'Edit')
		await clickButton(wrapper, 'Save')
		await flushPromises()

		expect(updateAssembly.mock.calls[0][1].language).toBeUndefined()
		expect(changeLanguage).not.toHaveBeenCalled()
	})

	it('shows a plain-language reason when a session is still being recorded', async () => {
		changeLanguage.mockRejectedValue(new Error('409: SESSION_ACTIVE'))
		const wrapper = await mountOverview()
		await clickButton(wrapper, 'Edit')
		await wrapper.find('#cz-assembly-language').setValue('it')
		await clickButton(wrapper, 'Continue')
		await flushPromises()

		expect(wrapper.find('.cz-error').text()).toBe('Finish the session being recorded first.')
	})

	it('cancelling the confirmation leaves the language untouched', async () => {
		const wrapper = await mountOverview()
		await clickButton(wrapper, 'Edit')
		await wrapper.find('#cz-assembly-language').setValue('it')
		await wrapper.findAll('button').find((b) => b.text() === 'Cancel' && b.element.closest('.cz-modal'))!.trigger('click')
		await flushPromises()

		expect(changeLanguage).not.toHaveBeenCalled()
		expect((wrapper.find('#cz-assembly-language').element as HTMLSelectElement).value).toBe('en')
	})
})

describe('audio retention', () => {
	it('defaults to the instance default', async () => {
		const wrapper = await mountOverview()
		await clickButton(wrapper, 'Edit')
		await clickButton(wrapper, 'Save')
		await flushPromises()

		expect(updateAssembly.mock.calls[0][1]).toMatchObject({ audio_retention_days: null, zero_retention: false })
	})

	it('saves the chosen number of days', async () => {
		const wrapper = await mountOverview()
		await clickButton(wrapper, 'Edit')
		const radios = wrapper.findAll('[data-test="retention"] input[type="radio"]')
		await radios[1].setValue() // "days"
		await wrapper.find('[data-test="retention"] input[type="number"]').setValue(45)
		await clickButton(wrapper, 'Save')
		await flushPromises()

		expect(updateAssembly.mock.calls[0][1]).toMatchObject({ audio_retention_days: 45, zero_retention: false })
	})

	it('sends zero retention without resending audio_retention_days', async () => {
		const wrapper = await mountOverview()
		await clickButton(wrapper, 'Edit')
		const radios = wrapper.findAll('[data-test="retention"] input[type="radio"]')
		await radios[2].setValue() // "zero"
		await clickButton(wrapper, 'Save')
		await flushPromises()

		const sent = updateAssembly.mock.calls[0][1]
		expect(sent.zero_retention).toBe(true)
		expect(sent.audio_retention_days).toBeUndefined()
	})

	it('shows when zero retention already ran, with nothing left to change', async () => {
		const wrapper = await mountOverview({
			...ASSEMBLY,
			zero_retention: true,
			zero_retention_done_at: '2026-10-12T09:30:00Z',
		})
		await clickButton(wrapper, 'Edit')

		expect(wrapper.find('[data-test="retention"]').text()).toContain('Zero retention applied on')
		expect(wrapper.find('[data-test="retention"] input[type="radio"]').exists()).toBe(false)
	})
})

describe('a session with no planned time', () => {
	it('shows "No planned time" instead of "0 min" in the sessions list', async () => {
		const wrapper = await mountOverview({
			...ASSEMBLY,
			rounds: [{ ...ASSEMBLY.rounds[0], duration_minutes: 0 }],
		})

		expect(wrapper.text()).toContain('No planned time')
		expect(wrapper.text()).not.toContain('0 min')
	})
})
