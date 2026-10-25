// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * A session with no planned duration (0 minutes — the table decides when it
 * is done) used to show "0 minutes" on the round picker, which reads as
 * broken rather than deliberate.
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

const ROUND = {
	id: 'round-1', position: 1, title: 'Mobility', question: 'What should change?',
	status: 'ACTIVE', duration_minutes: 0, recorded_state: null,
}
const SESSION = {
	session_token: 'tok', table_number: 1,
	assembly: { id: 'a1', name: 'Bologna', language: 'en', recording_mode: 'independent' },
	rounds: [ROUND],
}

beforeEach(() => {
	status.mockReset()
	Object.defineProperty(navigator, 'mediaDevices', {
		value: { getUserMedia: vi.fn().mockRejectedValue(new Error('no mic in test')) },
		configurable: true,
	})
})

describe('Preflight with a session that has no planned duration', () => {
	it('says there is no planned time instead of "0 minutes"', async () => {
		const wrapper = mountWithI18n(Preflight, { props: { session: SESSION } })
		await flushPromises()

		expect(wrapper.text()).toContain('No planned time')
		expect(wrapper.text()).not.toContain('0 minutes')
	})
})
