// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Is this a computer's browser rather than a phone's? A laptop recorded the
 * 2026-10-11 field test and lost between three and twenty-two minutes per
 * recording while its tab was in the background. The recorder works there,
 * but the table must be told what it costs — nothing is blocked.
 */
export function desktopBrowser(userAgent: string = navigator.userAgent): boolean {
	return !/Android|iPhone|iPad|iPod|Mobile|Mobi|Tablet/i.test(userAgent)
}
