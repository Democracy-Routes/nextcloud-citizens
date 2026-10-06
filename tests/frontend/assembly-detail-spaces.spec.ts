// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Plan → Run → Results (0.7): the assembly's nine tabs grouped into three
 * spaces under a timeline. The space opens where the event is — Plan before
 * it starts, Run while a session is live, Results once it is closed — and
 * the old tab ids keep working, so the Overview's "go to QR codes" link and
 * a fresh assembly's QR landing still resolve.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AssemblyDetail from '../../frontend/src/components/AssemblyDetail.vue'
import { mountWithI18n } from './support/mount'

const getAssembly = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	BASE: '',
	api: {
		getAssembly: (...args: unknown[]) => getAssembly(...args),
		deleteAssembly: vi.fn(),
		// the tabs' own calls, enough for them to mount quietly
		listParticipants: vi.fn().mockResolvedValue([]),
		getInvites: vi.fn().mockResolvedValue([]),
		listInvites: vi.fn().mockResolvedValue([]),
		roundMonitor: vi.fn().mockResolvedValue(null),
		roundMessages: vi.fn().mockResolvedValue([]),
		roundInterventions: vi.fn().mockResolvedValue([]),
		roundReadiness: vi.fn().mockResolvedValue(null),
		getReport: vi.fn().mockResolvedValue(null),
		report: vi.fn().mockResolvedValue(null),
		listRecordings: vi.fn().mockResolvedValue([]),
		getFindings: vi.fn().mockResolvedValue(null),
		findings: vi.fn().mockResolvedValue(null),
		getProgress: vi.fn().mockResolvedValue(null),
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
	rounds: [
		{ id: 'r1', position: 1, title: 'Problems', question: 'Q1', duration_minutes: 20, status: 'NOT_STARTED', started_at: null, ended_at: null },
		{ id: 'r2', position: 2, title: 'Proposals', question: 'Q2', duration_minutes: 20, status: 'NOT_STARTED', started_at: null, ended_at: null },
	],
}

beforeEach(() => {
	getAssembly.mockReset()
})

async function mountDetail(assembly: Record<string, unknown>, props: Record<string, unknown> = {}) {
	getAssembly.mockResolvedValue(assembly)
	const wrapper = mountWithI18n(AssemblyDetail, {
		props: { assemblyId: 'a1', ...props },
		global: { stubs: { OverviewTab: true, RoundsTab: true, ParticipantsTab: true, TablesTab: true, QrTab: true, MonitorTab: true, AnalysisTab: true, ReportTab: true, FilesTab: true } },
	})
	await flushPromises()
	return wrapper
}

function activeSpace(wrapper: ReturnType<typeof mountWithI18n>): string {
	return wrapper.find('[data-test="spaces"] .cz-tab--active').text()
}

describe('the assembly detail spaces', () => {
	it('opens on Plan before the event, with the Overview sub-tab and the timeline', async () => {
		const wrapper = await mountDetail(ASSEMBLY)
		expect(activeSpace(wrapper)).toBe('Plan')
		expect(wrapper.find('[data-test="subtabs"] .cz-tab--active').text()).toBe('Overview')
		expect(wrapper.find('[data-test="timeline"]').exists()).toBe(true)
		expect(wrapper.findComponent({ name: 'OverviewTab' }).exists()).toBe(true)
	})

	it('opens on Run while a session is live, and Run has no sub-tabs', async () => {
		const wrapper = await mountDetail({
			...ASSEMBLY, status: 'ACTIVE',
			rounds: [{ ...ASSEMBLY.rounds[0], status: 'ACTIVE' }, ASSEMBLY.rounds[1]],
		})
		expect(activeSpace(wrapper)).toBe('Run')
		expect(wrapper.find('[data-test="subtabs"]').exists()).toBe(false)
		expect(wrapper.findComponent({ name: 'MonitorTab' }).exists()).toBe(true)
	})

	it('opens on Results once the assembly is closed', async () => {
		const wrapper = await mountDetail({ ...ASSEMBLY, status: 'COMPLETE', closed_at: '2026-10-06T10:00:00Z' })
		expect(activeSpace(wrapper)).toBe('Results')
		expect(wrapper.find('[data-test="subtabs"] .cz-tab--active').text()).toBe('Report')
	})

	it('lands a freshly created assembly on its QR codes inside Plan', async () => {
		const wrapper = await mountDetail(ASSEMBLY, { freshInvites: [{ table_number: 1, url: 'u', qr_svg: '<svg/>' }] })
		expect(activeSpace(wrapper)).toBe('Plan')
		expect(wrapper.find('[data-test="subtabs"] .cz-tab--active').text()).toBe('QR codes')
	})

	it('switches space and sub-tab from the timeline and keeps the old tab ids working', async () => {
		const wrapper = await mountDetail(ASSEMBLY)
		await wrapper.find('[data-test="timeline-2"]').trigger('click')
		expect(activeSpace(wrapper)).toBe('Run')
		// the Overview's navigate event still names a tab id
		await wrapper.findAll('[data-test="spaces"] .cz-tab')[0].trigger('click')
		const overview = wrapper.findComponent({ name: 'OverviewTab' })
		overview.vm.$emit('navigate', 'qr')
		await flushPromises()
		expect(wrapper.find('[data-test="subtabs"] .cz-tab--active').text()).toBe('QR codes')
		// and Results' sub-tabs are the three result tabs
		await wrapper.findAll('[data-test="spaces"] .cz-tab')[2].trigger('click')
		expect(wrapper.findAll('[data-test="subtabs"] .cz-tab').map((t) => t.text())).toEqual(['Analysis', 'Report', 'Files'])
	})
})
