// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Preflight must not offer a round the server already has.
 *
 * It derived its round list from the join snapshot, which nothing refreshed —
 * so after a failed sync and Back the just-recorded round was re-offered,
 * 409'd by the server, and the report button never appeared. It now keeps the
 * list live from its own status poll.
 */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import Preflight from '../../frontend/src/recorder/components/Preflight.vue'
import { mountWithI18n } from './support/mount'

const status = vi.fn()

vi.mock('../../frontend/src/recorder/api', async () => {
	const actual = await vi.importActual<Record<string, unknown>>('../../frontend/src/recorder/api')
	return { ...actual, recorderApi: { status: (...a: unknown[]) => status(...a) } }
})
vi.mock('../../frontend/src/recorder/useWakeLock', () => ({ useWakeLock: vi.fn() }))
vi.mock('../../frontend/src/recorder/engine', () => ({ pickMimeType: () => 'audio/webm' }))
vi.mock('../../frontend/src/recorder/idb', () => ({ idb: { selfTest: vi.fn().mockResolvedValue(undefined) } }))

const ROUND = { id: 'round-1', position: 1, title: 'Mobility', question: 'What should change?',
	status: 'ACTIVE', duration_minutes: 30 }
const SESSION = {
	session_token: 'tok', table_number: 1,
	assembly: { id: 'a1', name: 'Bologna', language: 'en', recording_mode: 'independent' },
	rounds: [{ ...ROUND, recorded_state: null }],
}

beforeEach(() => {
	status.mockReset()
	Object.defineProperty(navigator, 'mediaDevices', {
		value: { getUserMedia: vi.fn().mockRejectedValue(new Error('no mic in test')) },
		configurable: true,
	})
})

describe('Preflight keeping its round list fresh', () => {
	it('drops a round the poll reports as already recorded, and shows the report', async () => {
		// the server now holds this round (e.g. a sync that just failed on the
		// phone actually landed) and the report is ready
		status.mockResolvedValue({
			rounds: [{ ...ROUND, recorded_state: 'AUDIO_READY' }],
			report_available: true,
		})
		const wrapper = mountWithI18n(Preflight, { props: { session: SESSION } })
		await flushPromises()

		// the stale prop no longer wins: the round is not re-offered to record
		expect(wrapper.text()).not.toContain('What should change?')
		// and the report button the stale list used to hide now appears
		expect(wrapper.findAll('button').some((b) => /report/i.test(b.text()))).toBe(true)
	})

	it('still offers an open round the server confirms is open', async () => {
		status.mockResolvedValue({
			rounds: [{ ...ROUND, recorded_state: null }],
			report_available: false,
		})
		const wrapper = mountWithI18n(Preflight, { props: { session: SESSION } })
		await flushPromises()

		expect(wrapper.text()).toContain('What should change?')
	})
})
