// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Short cues so a table knows the recording state without looking at the
 * phone: a rising double-tone when recording starts, a falling one when it
 * stops, the rising one again when the microphone comes back after an
 * interruption, a soft single chime for an organizer's message, a short
 * alert for a technical warning. Everyone at the table hears the moment
 * recording begins — which is also what the consent they gave refers to.
 *
 * Generated with WebAudio (no files to load, nothing to cache); the level is
 * a per-phone setting. The recorder engine is not involved.
 */
export type SoundLevel = 'normal' | 'quiet' | 'off'
export type SoundKind = 'start' | 'stop' | 'resume' | 'message' | 'alert'

const KEY = 'citizens-recorder-sounds'
const GAIN: Record<SoundLevel, number> = { normal: 0.35, quiet: 0.12, off: 0 }

/** The phone's level, or the default the screen proposes (assemblies: normal;
 * a spontaneous session: quiet). */
export function soundLevel(fallback: SoundLevel = 'normal'): SoundLevel {
	try {
		const stored = localStorage.getItem(KEY)
		if (stored === 'normal' || stored === 'quiet' || stored === 'off') return stored
	} catch {
		/* private mode */
	}
	return fallback
}

export function setSoundLevel(level: SoundLevel): void {
	try {
		localStorage.setItem(KEY, level)
	} catch {
		/* private mode: lasts until reload */
	}
}

let context: AudioContext | null = null

function audioContext(): AudioContext | null {
	const Ctor = (window as Window & { AudioContext?: typeof AudioContext; webkitAudioContext?: typeof AudioContext })
		.AudioContext ?? (window as Window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
	if (!Ctor) return null
	if (!context) context = new Ctor()
	return context
}

/** Each cue as (frequency Hz, start s, length s) notes. */
const NOTES: Record<SoundKind, Array<[number, number, number]>> = {
	start: [[660, 0, 0.12], [880, 0.14, 0.18]],
	stop: [[880, 0, 0.12], [660, 0.14, 0.18]],
	resume: [[660, 0, 0.12], [880, 0.14, 0.18]],
	message: [[784, 0, 0.22]],
	alert: [[523, 0, 0.1], [523, 0.16, 0.1], [523, 0.32, 0.1]],
}

export function play(kind: SoundKind, level: SoundLevel = soundLevel()): boolean {
	const gain = GAIN[level]
	if (!gain) return false
	const ctx = audioContext()
	if (!ctx) return false
	try {
		if (ctx.state === 'suspended') void ctx.resume()
		const now = ctx.currentTime
		for (const [frequency, at, length] of NOTES[kind]) {
			const oscillator = ctx.createOscillator()
			const envelope = ctx.createGain()
			oscillator.type = 'sine'
			oscillator.frequency.value = frequency
			envelope.gain.setValueAtTime(0, now + at)
			envelope.gain.linearRampToValueAtTime(gain, now + at + 0.02)
			envelope.gain.linearRampToValueAtTime(0, now + at + length)
			oscillator.connect(envelope)
			envelope.connect(ctx.destination)
			oscillator.start(now + at)
			oscillator.stop(now + at + length + 0.02)
		}
		return true
	} catch {
		return false // an audio context that refused: silence is not a failure
	}
}
