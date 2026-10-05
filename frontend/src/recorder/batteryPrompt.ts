// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * When a recording phone should ask for a backup, from its battery and the
 * table's recorder count. The only thing that prevents a phone dying
 * mid-session is a second phone recording beside it before it does; nothing
 * here is automatic and the engine is not involved.
 *
 * - `low` (≤ 15 %): this is the table's only recorder — suggest a backup.
 * - `critical` (≤ 8 %): show the handover code and say when to tap Finish.
 * - `none`: a healthy phone, an unknown battery (Safari, Firefox), or a table
 *   that already has another recorder, which is the backup.
 */
export type BatteryPrompt = 'none' | 'low' | 'critical'

export const LOW_BATTERY = 0.15
export const CRITICAL_BATTERY = 0.08

export function batteryPrompt(level: number | undefined, recorders: number | undefined): BatteryPrompt {
	if (typeof level !== 'number') return 'none'
	// an older session without the table summary is treated as alone: asking
	// one time too many beats staying silent while the phone dies
	if ((recorders ?? 1) > 1) return 'none'
	if (level <= CRITICAL_BATTERY) return 'critical'
	if (level <= LOW_BATTERY) return 'low'
	return 'none'
}
