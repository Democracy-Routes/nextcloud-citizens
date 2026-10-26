// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/** The About tab: read-only facts about the installation. */
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../frontend/src/api'
import AboutTab from '../../frontend/src/components/settings/AboutTab.vue'
import { mountWithI18n } from './support/mount'

const about = vi.fn()

vi.mock('../../frontend/src/api', () => ({
	api: { about: (...a: unknown[]) => about(...a) },
	ApiError: class extends Error {
		status: number
		constructor(status: number, message: string) {
			super(message)
			this.status = status
		}
	},
	BASE: '',
}))

const FIXTURE = {
	version: '0.8.0-test',
	schema_revision: '0038',
	stt_provider: 'vosk',
	vosk_mode: 'builtin',
	engine: {
		running: true,
		port: 2700,
		loaded: ['vosk-model-small-it-0.22'],
		in_use: { 'vosk-model-small-it-0.22': 1 },
		last_error: null,
		memory_available_bytes: 2 * 1048576 * 1024,
	},
	disk_free_gb: 12.5,
	storage_ok: true,
	jobs: {
		queued: 2,
		running: 0,
		retry: 0,
		failed: 1,
		newest_failure: { type: 'analysis', last_error: 'model unreachable', updated_at: '2026-10-20T10:00:00Z' },
	},
	last_sweep_at: null,
}

describe('AboutTab', () => {
	beforeEach(() => {
		about.mockReset()
	})

	it('shows version, engine, storage and documentation', async () => {
		about.mockResolvedValue(FIXTURE)
		const wrapper = mountWithI18n(AboutTab)
		await flushPromises()

		const version = wrapper.get('[data-test="about-version"]').text()
		expect(version).toContain('0.8.0-test')
		expect(version).toContain('0038')

		const engine = wrapper.get('[data-test="about-engine"]').text()
		expect(engine).toContain('Running')
		expect(engine).toContain('vosk-model-small-it-0.22')

		const storage = wrapper.get('[data-test="about-storage"]')
		const rows = storage.findAll('dt').map((dt) => [dt.text(), dt.element.nextElementSibling?.textContent?.trim()])
		expect(rows).toContainEqual(['Queued', '2'])
		expect(storage.text()).toContain('model unreachable')
		expect(storage.text()).toContain('not yet')

		const links = wrapper.get('[data-test="about-docs"]').findAll('a')
		expect(links).toHaveLength(4)
		const ends = ['administration.md', 'facilitator-guide.md', 'event-checklist.md', 'privacy.md']
		ends.forEach((end, i) => expect(links[i].attributes('href')).toMatch(new RegExp(`${end}$`)))
	})

	it('renders the error when the request fails', async () => {
		about.mockImplementation(async () => {
			throw new ApiError(409, 'boom from server')
		})
		const wrapper = mountWithI18n(AboutTab)
		await flushPromises()
		expect(wrapper.text()).toContain('boom from server')
	})
})
