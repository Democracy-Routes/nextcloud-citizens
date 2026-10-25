// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/** One way to render each kind of value.
 *
 * The same seven-minute recording appeared as "7:05" in the Files tab and
 * "07:05" in the Live tab, and byte sizes were formatted by two separate
 * copies of the same function. Small, but it is the sort of thing that makes a
 * facilitator wonder whether they are looking at the same recording.
 */
import { t } from './i18n'

/** mm:ss, zero-padded. An em dash for nothing, never "0:00" — a recording of
 * unknown length and one of zero length are different facts. */
export function duration(seconds: number | null | undefined): string {
	if (!seconds && seconds !== 0) return '—'
	if (seconds <= 0) return '—'
	const minutes = Math.floor(seconds / 60)
	return `${String(minutes).padStart(2, '0')}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`
}

export function bytes(value: number | null | undefined): string {
	if (!value) return '—'
	if (value < 1024 * 1024) return t('organizer.settings.format.kb', { n: Math.round(value / 1024) })
	if (value < 1024 * 1024 * 1024)
		return t('organizer.settings.format.mb', { n: (value / 1024 / 1024).toFixed(1) })
	return t('organizer.settings.format.gb', { n: (value / 1024 / 1024 / 1024).toFixed(2) })
}

/** A position INSIDE a recording, where 00:00 is a real answer — unlike
 * duration(), for which zero means "we do not know how long this is". */
export function timestamp(seconds: number): string {
	const minutes = Math.floor(seconds / 60)
	return `${String(minutes).padStart(2, '0')}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`
}

/** How long ago, for a device's last contact. */
export function relativeAge(seconds: number | null | undefined): string {
	if (seconds === null || seconds === undefined) return '—'
	if (seconds < 90) return t('organizer.settings.format.secondsAgo', { n: Math.round(seconds) })
	if (seconds < 90 * 60) return t('organizer.settings.format.minutesAgo', { n: Math.round(seconds / 60) })
	if (seconds < 48 * 3600) return t('organizer.settings.format.hoursAgo', { n: Math.round(seconds / 3600) })
	return t('organizer.settings.format.daysAgo', { n: Math.round(seconds / 86400) })
}

export function clockTime(value: Date | string | null | undefined): string {
	if (!value) return '—'
	const date = typeof value === 'string' ? new Date(value) : value
	if (Number.isNaN(date.getTime())) return '—'
	return date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}
