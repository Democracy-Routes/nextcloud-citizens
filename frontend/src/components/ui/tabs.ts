// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Ids that pair a tab with the panel it controls.
 *
 * Both sides have to agree on these strings, or aria-controls points at
 * nothing and the relationship a screen reader relies on does not exist.
 */
export interface TabItem {
	id: string
	label: string
	icon?: string
}

export function tabId(prefix: string, id: string): string {
	return `${prefix}-tab-${id}`
}

export function panelId(prefix: string, id: string): string {
	return `${prefix}-panel-${id}`
}
