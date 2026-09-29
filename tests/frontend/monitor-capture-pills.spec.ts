// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The two things about a phone the organizer can still act on mid-round.
 *
 * "capture interrupted": the phone says it is recording but no audio has come
 * out of the microphone for half a minute — somebody should pick it up.
 * "screen may lock": the phone holds no wake lock, so its screen will go off
 * at its own timeout unless auto-lock is set to Never by hand. Neither can be
 * read off a heartbeat from an older recorder build, so absence shows nothing.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MonitorTab from '../../frontend/src/components/MonitorTab.vue'
import { mountWithI18n } from './support/mount'

const roundMonitor = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: {
		roundMonitor: (...a: unknown[]) => roundMonitor(...a),
		startRound: vi.fn(),
		endRound: vi.fn(),
		requestTranscription: vi.fn(),
		recordingTranscript: vi.fn(),
		deviceLogs: vi.fn(),
	},
	ApiError: class extends Error {},
	BASE: '',
}))

const ASSEMBLY = {
	id: 'a1',
	name: 'Bologna',
	rounds: [{ id: 'round-1', position: 1, title: 'R1', status: 'ACTIVE' }],
}

function monitorWith(status: Record<string, unknown>, connected = true) {
	return {
		round_id: 'round-1',
		status: 'ACTIVE',
		started_at: new Date().toISOString(),
		duration_minutes: 30,
		recording_mode: 'orchestrated',
		tables_ready: 1,
		tables_total: 1,
		rounds: [{ id: 'round-1', position: 1, title: 'R1', status: 'ACTIVE' }],
		tables: [
			{
				table_id: 't1',
				number: 1,
				device: { connected, seconds_since_contact: connected ? 3 : 90, status },
				armed: false,
				local_recording_safe: true,
				recording: {
					id: 'rec-1',
					state: 'RECORDING',
					started_at: null,
					received_chunks: 4,
					total_chunks: null,
					error_code: '',
				},
			},
		],
	}
}

beforeEach(() => roundMonitor.mockReset())

async function shown(status: Record<string, unknown>, connected = true) {
	roundMonitor.mockResolvedValue(monitorWith(status, connected))
	const wrapper = mountWithI18n(MonitorTab, { props: { assembly: ASSEMBLY } })
	await flushPromises()
	return wrapper.text()
}

describe('the capture and screen pills', () => {
	it('flags a recording phone whose microphone has gone quiet', async () => {
		const text = await shown({ storage_ok: true, recording_active: true, capture_ok: false })
		expect(text).toContain('capture interrupted')
	})

	it('puts the interruption ahead of a storage error', async () => {
		const text = await shown({ storage_ok: false, recording_active: true, capture_ok: false })
		expect(text).toContain('capture interrupted')
		expect(text).not.toContain('storage error')
	})

	it('says nothing when audio is arriving', async () => {
		const text = await shown({ storage_ok: true, recording_active: true, capture_ok: true })
		expect(text).not.toContain('capture interrupted')
	})

	it('leaves a stale phone to the stale pill', async () => {
		const text = await shown({ storage_ok: true, recording_active: true, capture_ok: false }, false)
		expect(text).not.toContain('capture interrupted')
	})

	it('flags a phone that cannot keep its screen on', async () => {
		const text = await shown({ storage_ok: true, screen_awake: false })
		expect(text).toContain('screen may lock')
	})

	it('shows neither for an older recorder that reports nothing', async () => {
		const text = await shown({ storage_ok: true, recording_active: true })
		expect(text).not.toContain('capture interrupted')
		expect(text).not.toContain('screen may lock')
	})
})
