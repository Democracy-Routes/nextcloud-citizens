// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The facilitator's own phone (0.7): one table's view — the session's
 * question and clock, the people and their consent, the organizer's
 * messages — and from it a prompt to the table, the table's hand, the
 * registration code, and the hand-over to the recorder app.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import FacilitatorPage from '../../frontend/src/recorder/components/FacilitatorPage.vue'
import { mountWithI18n } from './support/mount'

const facilitatorStatus = vi.fn()
const facilitatorPrompt = vi.fn()
const facilitatorHelp = vi.fn()
const facilitatorCode = vi.fn()
const facilitatorMessageSeen = vi.fn()
const facilitatorLeave = vi.fn()
const adviceDismiss = vi.fn()
const adviceSend = vi.fn()
const adviceFeedback = vi.fn()

vi.mock('../../frontend/src/recorder/api', () => ({
	recorderApi: {
		facilitatorStatus: (...args: unknown[]) => facilitatorStatus(...args),
		facilitatorPrompt: (...args: unknown[]) => facilitatorPrompt(...args),
		facilitatorHelp: (...args: unknown[]) => facilitatorHelp(...args),
		facilitatorCode: (...args: unknown[]) => facilitatorCode(...args),
		facilitatorMessageSeen: (...args: unknown[]) => facilitatorMessageSeen(...args),
		facilitatorLeave: (...args: unknown[]) => facilitatorLeave(...args),
		facilitatorHeartbeat: vi.fn().mockResolvedValue({ ok: true }),
		facilitatorAdviceDismiss: (...args: unknown[]) => adviceDismiss(...args),
		facilitatorAdviceSend: (...args: unknown[]) => adviceSend(...args),
		facilitatorAdviceFeedback: (...args: unknown[]) => adviceFeedback(...args),
	},
	RecorderApiError: class extends Error {},
}))

const STATUS = {
	assembly: { id: 'a1', kind: 'assembly', name: 'Bologna', language: 'en', recording_mode: 'orchestrated' },
	assembly_closed: false,
	table_number: 4,
	color_key: 'purple',
	round: {
		id: 'r1', position: 1, title: 'Problems', question: 'What is broken in our neighbourhood?',
		objective: 'A list of three problems', status: 'ACTIVE', duration_minutes: 20,
		started_at: '2026-10-06T09:00:00Z', ends_at: '2026-10-06T09:20:00Z', seconds_left: 7 * 60 + 10,
	},
	rounds: [{ id: 'r1', position: 1, title: 'Problems', status: 'ACTIVE' }],
	consent: { mode: 'required', registered: 3, consenting: 2, can_record: true },
	participants: [
		{ label: 'P001', name: 'Anna', recording_consent: true },
		{ label: 'P002', name: 'Bruno', recording_consent: true },
		{ label: 'P003', name: 'Carla', recording_consent: false },
	],
	recorders: 1,
	messages: [],
	help: null,
	speaking: null,
	advice: [],
	capabilities: { live_speaking_balance: false, ai_facilitator: false },
}

beforeEach(() => {
	facilitatorStatus.mockReset()
	facilitatorPrompt.mockReset()
	facilitatorHelp.mockReset()
	facilitatorCode.mockReset()
	facilitatorMessageSeen.mockReset()
	facilitatorLeave.mockReset()
	facilitatorStatus.mockResolvedValue(STATUS)
})

async function mountPage(props: Record<string, unknown> = {}) {
	const wrapper = mountWithI18n(FacilitatorPage, { props: { token: 'fac-token', ...props } })
	await flushPromises()
	return wrapper
}

describe('the facilitator page', () => {
	it('shows the session, its clock, the question and the people', async () => {
		const wrapper = await mountPage()
		expect(wrapper.find('[data-test="clock"]').text()).toBe('8 min left')
		expect(wrapper.find('[data-test="question"]').text()).toBe('What is broken in our neighbourhood?')
		expect(wrapper.text()).toContain('A list of three problems')
		expect(wrapper.find('[data-test="people"]').text()).toContain('2 of 3 registered consented')
		expect(wrapper.find('[data-test="people"]').text()).toContain('Carla')
		expect(wrapper.find('[data-test="speaking"]').text()).toContain('Not available with this transcription engine')
		// the AI facilitator is off: no advice card at all
		expect(wrapper.find('[data-test="advice"]').exists()).toBe(false)
	})

	it('says when the time is up, and when no session is running', async () => {
		facilitatorStatus.mockResolvedValue({ ...STATUS, round: { ...STATUS.round, seconds_left: -200 } })
		let wrapper = await mountPage()
		expect(wrapper.find('[data-test="clock"]').text()).toBe('Over by 3 min')
		expect(wrapper.find('[data-test="clock"]').classes()).toContain('rc-fac-clock--over')

		facilitatorStatus.mockResolvedValue({
			...STATUS, round: { ...STATUS.round, status: 'NOT_STARTED', seconds_left: null, ends_at: null },
		})
		wrapper = await mountPage()
		expect(wrapper.find('[data-test="not-running"]').text()).toBe('No session is running')
	})

	it('sends a prompt to the table and clears the box', async () => {
		facilitatorPrompt.mockResolvedValue({ id: 9, kind: 'PROMPT', text: 'Has everyone spoken?', sound: true })
		const wrapper = await mountPage()
		const send = wrapper.find('[data-test="send-prompt"]')
		expect(send.attributes('disabled')).toBeDefined()
		await wrapper.find('[data-test="prompt-text"]').setValue('Has everyone spoken?')
		await send.trigger('click')
		await flushPromises()
		expect(facilitatorPrompt).toHaveBeenCalledWith('fac-token', 'Has everyone spoken?')
		expect((wrapper.find('[data-test="prompt-text"]').element as HTMLTextAreaElement).value).toBe('')
		expect(wrapper.find('[data-test="sent"]').text()).toContain("Sent to the table's phones")
	})

	it('raises the table\'s hand and shows the organizer\'s messages once', async () => {
		facilitatorHelp.mockResolvedValue({
			id: 'h1', kind: 'PROCESS', table_number: 4, slot: 1, created_at: 'now', acknowledged_at: null,
		})
		facilitatorStatus.mockResolvedValue({
			...STATUS,
			messages: [{ id: 3, kind: 'TIME_LEFT', text: '5 minutes left', sound: false, created_at: 'now' }],
		})
		const wrapper = await mountPage()
		expect(wrapper.find('[data-test="messages"]').text()).toContain('5 minutes left')
		expect(facilitatorMessageSeen).toHaveBeenCalledWith('fac-token', 3)

		await wrapper.find('[data-test="need-help"]').trigger('click')
		await wrapper.find('[data-test="help-PROCESS"]').trigger('click')
		await flushPromises()
		expect(facilitatorHelp).toHaveBeenCalledWith('fac-token', 'PROCESS')
		expect(wrapper.find('[data-test="help"]').text()).toContain('Organizer notified')
	})

	it('opens the registration code on this phone and hands over to the recorder app', async () => {
		facilitatorCode
			.mockResolvedValueOnce({ purpose: 'REGISTER_PARTICIPANT', url: 'https://x/recorder.html#/register/REG123' })
			.mockResolvedValueOnce({ purpose: 'ADD_RECORDER_TO_TABLE', url: 'https://x/recorder.html#/join/JOIN456' })
		const wrapper = await mountPage()
		await wrapper.find('[data-test="register"]').trigger('click')
		await flushPromises()
		expect(facilitatorCode).toHaveBeenCalledWith('fac-token', 'REGISTER_PARTICIPANT')
		expect(wrapper.emitted('register')?.[0]).toEqual(['REG123'])

		await wrapper.find('[data-test="become-recorder"]').trigger('click')
		await wrapper.find('[data-test="become-recorder-confirm"]').trigger('click')
		await flushPromises()
		expect(facilitatorCode).toHaveBeenCalledWith('fac-token', 'ADD_RECORDER_TO_TABLE')
		expect(wrapper.emitted('becomeRecorder')?.[0]).toEqual(['https://x/recorder.html#/join/JOIN456'])
	})

	it('says so when already registered, and leaves cleanly', async () => {
		facilitatorLeave.mockResolvedValue({ ok: true })
		const wrapper = await mountPage({ registered: true })
		expect(wrapper.find('[data-test="registered"]').text()).toContain('You are registered at this table')
		expect(wrapper.find('[data-test="register"]').exists()).toBe(false)
		await wrapper.find('[data-test="leave"]').trigger('click')
		await flushPromises()
		expect(facilitatorLeave).toHaveBeenCalledWith('fac-token')
		expect(wrapper.emitted('forget')).toBeTruthy()
	})

	it('shows the AI facilitator\'s advice for the facilitator to judge', async () => {
		adviceDismiss.mockResolvedValue({})
		adviceSend.mockResolvedValue({ sent_to_table_at: 'now' })
		adviceFeedback.mockResolvedValue({})
		facilitatorStatus.mockResolvedValue({
			...STATUS,
			ai_facilitator: { level: 'normal', override: null, assembly_level: 'normal', instance_level: 'off', configured: true },
			capabilities: { live_speaking_balance: false, ai_facilitator: true },
			advice: [
				{ id: 'i1', kind: 'objective', text: 'What would make your list of three?', created_at: 'now' },
				{ id: 'i2', kind: 'time', text: 'Three minutes left — which problem matters most?', created_at: 'now' },
			],
		})
		const wrapper = await mountPage()
		const card = wrapper.find('[data-test="advice"]')
		expect(card.text()).toContain('Level: Normal')
		expect(wrapper.findAll('[data-test="advice-card"]')).toHaveLength(2)

		await wrapper.findAll('[data-test="advice-down"]')[0].trigger('click')
		expect(adviceFeedback).toHaveBeenCalledWith('fac-token', 'i1', false)
		await wrapper.findAll('[data-test="advice-dismiss"]')[0].trigger('click')
		await flushPromises()
		expect(adviceDismiss).toHaveBeenCalledWith('fac-token', 'i1')
		expect(wrapper.findAll('[data-test="advice-card"]')).toHaveLength(1)

		await wrapper.find('[data-test="advice-send"]').trigger('click')
		await flushPromises()
		expect(adviceSend).toHaveBeenCalledWith('fac-token', 'i2')
		expect(wrapper.find('[data-test="advice-sent"]').text()).toContain('Sent to the table')
	})

	it('has no hand to raise in a spontaneous Session', async () => {
		facilitatorStatus.mockResolvedValue({ ...STATUS, assembly: { ...STATUS.assembly, kind: 'session' } })
		const wrapper = await mountPage()
		expect(wrapper.find('[data-test="help"]').exists()).toBe(false)
	})
})
