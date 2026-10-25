// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The organizer's voice on the phone: a message rides the status poll, is
 * shown big, folds to one line, goes away — and the phone tells the server it
 * was shown, once, so the Live tab can say "delivered".
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import MessageBanner from '../../frontend/src/recorder/components/MessageBanner.vue'
import { useTableMessages } from '../../frontend/src/recorder/useTableMessages'
import { mountWithI18n } from './support/mount'

const messageSeen = vi.fn().mockResolvedValue({ ok: true })

vi.mock('../../frontend/src/recorder/api', () => ({
	recorderApi: { messageSeen: (...args: unknown[]) => messageSeen(...args) },
}))

const MESSAGE = { id: 7, kind: 'TIME_LEFT' as const, text: '5 minutes left', sound: false, created_at: 'now' }

describe('useTableMessages', () => {
	beforeEach(() => {
		messageSeen.mockClear()
	})

	it('shows the newest unseen message and sends one receipt for it', () => {
		const messages = useTableMessages('tok')
		messages.ingest({ messages: [{ ...MESSAGE, id: 6, text: 'older' }, MESSAGE] })
		expect(messages.current.value?.text).toBe('5 minutes left')
		expect(messageSeen).toHaveBeenCalledWith('tok', 7)
		// the same payload again (the receipt was lost): nothing new, no second receipt
		messages.ingest({ messages: [MESSAGE] })
		expect(messageSeen).toHaveBeenCalledTimes(1)
		messages.dismiss()
		expect(messages.current.value).toBeNull()
		// a newer message after dismissal is shown
		messages.ingest({ messages: [{ ...MESSAGE, id: 8, text: 'Wrap up' }] })
		expect(messages.current.value?.text).toBe('Wrap up')
		expect(messageSeen).toHaveBeenLastCalledWith('tok', 8)
	})

	it('ignores a status without messages (an older server)', () => {
		const messages = useTableMessages('tok')
		messages.ingest({})
		expect(messages.current.value).toBeNull()
		expect(messageSeen).not.toHaveBeenCalled()
	})
})

describe('MessageBanner', () => {
	beforeEach(() => {
		vi.useFakeTimers()
	})
	afterEach(() => {
		vi.useRealTimers()
	})

	it('is big, then one line, then gone', async () => {
		const wrapper = mountWithI18n(MessageBanner, { props: { message: MESSAGE } })
		expect(wrapper.text()).toContain('From the organizer')
		expect(wrapper.text()).toContain('5 minutes left')
		expect(wrapper.classes()).not.toContain('rc-message--compact')
		vi.advanceTimersByTime(6_000)
		await wrapper.vm.$nextTick()
		expect(wrapper.classes()).toContain('rc-message--compact')
		expect(wrapper.text()).not.toContain('From the organizer')
		expect(wrapper.emitted('dismiss')).toBeFalsy()
		vi.advanceTimersByTime(90_000)
		expect(wrapper.emitted('dismiss')).toHaveLength(1)
	})

	it('can be closed by hand', async () => {
		const wrapper = mountWithI18n(MessageBanner, { props: { message: MESSAGE } })
		await wrapper.find('button').trigger('click')
		expect(wrapper.emitted('dismiss')).toHaveLength(1)
	})
})
