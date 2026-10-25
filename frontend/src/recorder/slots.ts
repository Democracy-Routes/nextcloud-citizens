// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Recorder slot 1 is "A", 2 is "B" … 27 is "AA" — the same letters the
 * server prints (services/table_recordings.slot_label). */
export function slotLabel(slot: number): string {
	let label = ''
	let n = Math.max(slot, 1)
	while (n > 0) {
		const remainder = (n - 1) % 26
		label = String.fromCharCode(65 + remainder) + label
		n = Math.floor((n - 1) / 26)
	}
	return label
}
