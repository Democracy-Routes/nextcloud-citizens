// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * One way to render each kind of value.
 *
 * The same seven-minute recording appeared as "7:05" in the Files tab and
 * "07:05" in the Live tab, and byte sizes had two separate implementations.
 * Small on its own, but it is the sort of inconsistency that makes somebody
 * wonder whether they are looking at the same recording.
 */
import { describe, expect, it } from 'vitest'
import { bytes, clockTime, duration, relativeAge, timestamp } from '../../frontend/src/format'

describe('duration', () => {
	it('is always zero-padded', () => {
		expect(duration(425)).toBe('07:05')
	})

	it('says nothing rather than "00:00" when the length is unknown', () => {
		// a recording of unknown length and one of zero length are different
		// facts, and only one of them is worth stating
		expect(duration(null)).toBe('—')
		expect(duration(undefined)).toBe('—')
		expect(duration(0)).toBe('—')
	})

	it('keeps counting past an hour rather than wrapping', () => {
		expect(duration(3725)).toBe('62:05')
	})
})

describe('timestamp', () => {
	it('treats the start of a recording as a real position', () => {
		// unlike duration(), where zero means "unknown"
		expect(timestamp(0)).toBe('00:00')
	})

	it('matches duration for everything else', () => {
		expect(timestamp(425)).toBe(duration(425))
	})
})

describe('bytes', () => {
	it('scales to the unit that reads naturally', () => {
		expect(bytes(2048)).toBe('2 KB')
		expect(bytes(5 * 1024 * 1024)).toBe('5.0 MB')
		expect(bytes(3 * 1024 * 1024 * 1024)).toBe('3.00 GB')
	})

	it('renders nothing for nothing', () => {
		expect(bytes(0)).toBe('—')
		expect(bytes(null)).toBe('—')
	})
})

describe('relativeAge', () => {
	it('coarsens as the gap grows', () => {
		expect(relativeAge(30)).toBe('30s ago')
		expect(relativeAge(600)).toBe('10m ago')
		expect(relativeAge(7200)).toBe('2h ago')
		expect(relativeAge(3 * 86400)).toBe('3d ago')
	})

	it('admits when there has been no contact at all', () => {
		expect(relativeAge(null)).toBe('—')
	})
})

describe('clockTime', () => {
	it('handles a bad value without rendering "Invalid Date"', () => {
		expect(clockTime('not a date')).toBe('—')
		expect(clockTime(null)).toBe('—')
	})
})
