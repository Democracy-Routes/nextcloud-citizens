// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * S9: the assembly's name is the only thing the header shows worth its own
 * edit screen for one field, so it is click-to-edit in place — a pencil
 * turns the heading into an input; Enter or a blur with a real change saves
 * it through the ordinary update route and reloads, Escape (or no change)
 * does neither.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AssemblyDetail from '../../frontend/src/components/AssemblyDetail.vue'
import { mountWithI18n } from './support/mount'

const getAssembly = vi.fn()
const updateAssembly = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	BASE: '',
	api: {
		getAssembly: (...args: unknown[]) => getAssembly(...args),
		updateAssembly: (...args: unknown[]) => updateAssembly(...args),
		deleteAssembly: vi.fn(),
		listParticipants: vi.fn().mockResolvedValue([]),
		listInvites: vi.fn().mockResolvedValue([]),
		roundMonitor: vi.fn().mockResolvedValue(null),
		roundMessages: vi.fn().mockResolvedValue([]),
		roundInterventions: vi.fn().mockResolvedValue([]),
		registrationLink: vi.fn().mockResolvedValue({ url: null, registered: { total: 0, seated: 0 } }),
	},
}))

const ASSEMBLY = {
	id: 'a1',
	kind: 'assembly',
	name: 'Bologna',
	description: '',
	language: 'en',
	scheduled_at: null,
	status: 'DRAFT',
	recording_mode: 'orchestrated',
	expected_participants: 40,
	participant_count: 0,
	default_table_count: 5,
	analysis_instructions: '',
	auto_purge_device_audio: true,
	redact_names: '',
	closed_at: null,
	created_by: 'u',
	created_at: 'now',
	rounds: [],
}

beforeEach(() => {
	getAssembly.mockReset().mockResolvedValue(ASSEMBLY)
	updateAssembly.mockReset()
})

async function mountDetail() {
	const wrapper = mountWithI18n(AssemblyDetail, {
		props: { assemblyId: 'a1' },
		global: { stubs: { OverviewTab: true, RoundsTab: true, ParticipantsTab: true, TablesTab: true, QrTab: true, MonitorTab: true, AnalysisTab: true, ReportTab: true, FilesTab: true } },
	})
	await flushPromises()
	return wrapper
}

describe('renaming an assembly from its header', () => {
	it('turns the heading into an input, named for a screen reader', async () => {
		const wrapper = await mountDetail()
		expect(wrapper.find('h2').text()).toBe('Bologna')
		const rename = wrapper.find('[data-test="rename"]')
		expect(rename.attributes('aria-label')).toBe('Rename')

		await rename.trigger('click')
		expect(wrapper.find('h2').exists()).toBe(false)
		const input = wrapper.find('[data-test="rename-input"]')
		expect((input.element as HTMLInputElement).value).toBe('Bologna')
	})

	it('saves a changed name on Enter and reloads', async () => {
		updateAssembly.mockResolvedValue({ ...ASSEMBLY, name: 'Modena' })
		const wrapper = await mountDetail()
		// the initial load already consumed the default; queue what reload() sees
		getAssembly.mockResolvedValueOnce({ ...ASSEMBLY, name: 'Modena' })
		await wrapper.find('[data-test="rename"]').trigger('click')
		const input = wrapper.find('[data-test="rename-input"]')
		await input.setValue('Modena')
		await input.trigger('keyup.enter')
		await flushPromises()

		expect(updateAssembly).toHaveBeenCalledWith('a1', { name: 'Modena' })
		expect(getAssembly).toHaveBeenCalledTimes(2) // the initial load, then reload()
		expect(wrapper.find('[data-test="rename-input"]').exists()).toBe(false)
		expect(wrapper.find('h2').text()).toBe('Modena')
	})

	it('saves on blur when the name actually changed', async () => {
		updateAssembly.mockResolvedValue({ ...ASSEMBLY, name: 'Modena' })
		const wrapper = await mountDetail()
		await wrapper.find('[data-test="rename"]').trigger('click')
		const input = wrapper.find('[data-test="rename-input"]')
		await input.setValue('Modena')
		await input.trigger('blur')
		await flushPromises()

		expect(updateAssembly).toHaveBeenCalledWith('a1', { name: 'Modena' })
	})

	it('cancels on Escape without saving', async () => {
		const wrapper = await mountDetail()
		await wrapper.find('[data-test="rename"]').trigger('click')
		const input = wrapper.find('[data-test="rename-input"]')
		await input.setValue('Modena')
		await input.trigger('keyup.escape')
		await flushPromises()

		expect(updateAssembly).not.toHaveBeenCalled()
		expect(wrapper.find('h2').text()).toBe('Bologna')
	})

	it('never saves an empty name', async () => {
		const wrapper = await mountDetail()
		await wrapper.find('[data-test="rename"]').trigger('click')
		const input = wrapper.find('[data-test="rename-input"]')
		await input.setValue('   ')
		await input.trigger('keyup.enter')
		await flushPromises()

		expect(updateAssembly).not.toHaveBeenCalled()
		expect(wrapper.find('h2').text()).toBe('Bologna')
	})

	it('does nothing when the name was not actually changed', async () => {
		const wrapper = await mountDetail()
		await wrapper.find('[data-test="rename"]').trigger('click')
		const input = wrapper.find('[data-test="rename-input"]')
		await input.trigger('keyup.enter')
		await flushPromises()

		expect(updateAssembly).not.toHaveBeenCalled()
	})
})
