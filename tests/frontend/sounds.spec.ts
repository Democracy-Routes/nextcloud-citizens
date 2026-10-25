// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The table's cues: generated with WebAudio under a per-phone level, silent
 * when off, remembered across reloads.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { play, setSoundLevel, soundLevel } from '../../frontend/src/recorder/sounds'

const started: number[] = []

class FakeContext {
	state = 'running'
	currentTime = 0
	destination = {}
	createOscillator() {
		return {
			type: 'sine', frequency: { value: 0 }, connect: vi.fn(),
			start: (at: number) => started.push(at), stop: vi.fn(),
		}
	}
	createGain() {
		return { gain: { setValueAtTime: vi.fn(), linearRampToValueAtTime: vi.fn() }, connect: vi.fn() }
	}
	resume = vi.fn()
}

beforeEach(() => {
	started.length = 0
	localStorage.removeItem('citizens-recorder-sounds')
	;(window as unknown as { AudioContext: unknown }).AudioContext = FakeContext
})
afterEach(() => {
	delete (window as unknown as { AudioContext?: unknown }).AudioContext
})

describe('the table cues', () => {
	it('plays a two-note start cue and a single chime for a message', () => {
		expect(play('start', 'normal')).toBe(true)
		expect(started).toHaveLength(2)
		started.length = 0
		expect(play('message', 'quiet')).toBe(true)
		expect(started).toHaveLength(1)
	})

	it('is silent when off, and remembers the level', () => {
		expect(play('stop', 'off')).toBe(false)
		expect(started).toHaveLength(0)
		expect(soundLevel('quiet')).toBe('quiet')
		setSoundLevel('off')
		expect(soundLevel('normal')).toBe('off')
		expect(play('alert')).toBe(false)
	})
})
