// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The speaking-balance donut is an honest, anonymous estimate.
 *
 * It must render one arc and one legend row per voice, keep the voices
 * anonymous ("Voice A", never a name), and say in its own caption that the
 * numbers come from a single recording and measure talk-time, not influence.
 */
import { describe, expect, it } from 'vitest'
import SpeakingBalanceCard from '../../frontend/src/components/SpeakingBalanceCard.vue'
import type { SpeakingBalance } from '../../frontend/src/types'
import { mountWithI18n } from './support/mount'

const BALANCE: SpeakingBalance = {
	total_seconds: 300,
	from_recording_id: 'rec-1',
	voices: [
		{ label: 'A', seconds: 180, percent: 60 },
		{ label: 'B', seconds: 90, percent: 30 },
		{ label: 'Others', seconds: 30, percent: 10 },
	],
}

describe('the speaking-balance donut', () => {
	it('draws one arc and one legend row per voice', () => {
		const wrapper = mountWithI18n(SpeakingBalanceCard, { props: { balance: BALANCE } })

		// one background ring + three coloured arcs
		expect(wrapper.findAll('circle')).toHaveLength(4)
		expect(wrapper.findAll('.cz-speaking__legend li')).toHaveLength(3)
	})

	it('labels voices anonymously and shows their share', () => {
		const wrapper = mountWithI18n(SpeakingBalanceCard, { props: { balance: BALANCE } })
		const text = wrapper.text()

		expect(text).toContain('Voice A')
		expect(text).toContain('60%')
		expect(text).toContain('Others')
		// no diarization internals leak through
		expect(text).not.toContain('SPEAKER_')
	})

	it('is honest about what it measures', () => {
		const wrapper = mountWithI18n(SpeakingBalanceCard, { props: { balance: BALANCE } })
		const text = wrapper.text()

		expect(text).toContain('not identified by name')
		expect(text.toLowerCase()).toContain('talk-time')
	})
})
