// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/* Deliberation-report vocabulary for finding types — shared by the organizer
 * app and the recorder report screen. DB type values never change; only how
 * they are presented. Mirrors citizens/services/report_text.py and must
 * agree with it, or the same finding or round is named differently on screen
 * and in the export. */
import { t } from './i18n'

export const TYPE_ORDER = [
	'proposal',
	'agreement',
	'disagreement',
	'concern',
	'question',
	'minority_position',
	'new_idea',
] as const

/** @deprecated English-only, kept so a caller that still indexes this object
 * directly (rather than calling typeLabel()) keeps working. Prefer
 * typeLabel(), which follows the current locale. */
export const TYPE_LABELS: Record<string, string> = {
	proposal: 'Proposal',
	agreement: 'Point of consensus',
	disagreement: 'Point of divergence',
	concern: 'Concern',
	question: 'Open question',
	minority_position: 'Minority position',
	new_idea: 'Emerging idea',
}

function knownType(type: string): (typeof TYPE_ORDER)[number] | null {
	return (TYPE_ORDER as readonly string[]).includes(type) ? (type as (typeof TYPE_ORDER)[number]) : null
}

/** A finding type's singular label, in the current locale. */
export function typeLabel(type: string): string {
	const key = knownType(type)
	return key ? t(`organizer.results.labels.type.${key}`) : type.replaceAll('_', ' ')
}

/** A finding type's plural/group label, in the current locale. */
export function typeLabelPlural(type: string): string {
	const key = knownType(type)
	return key ? t(`organizer.results.labels.typePlural.${key}`) : type.replaceAll('_', ' ')
}

export function groupByType<T extends { type: string }>(
	findings: T[],
): Array<{ type: string; label: string; findings: T[] }> {
	const groups: Array<{ type: string; label: string; findings: T[] }> = []
	for (const type of TYPE_ORDER) {
		const matching = findings.filter((f) => f.type === type)
		if (matching.length) groups.push({ type, label: typeLabelPlural(type), findings: matching })
	}
	const leftover = findings.filter((f) => !TYPE_ORDER.includes(f.type as (typeof TYPE_ORDER)[number]))
	if (leftover.length) groups.push({ type: 'other', label: t('organizer.results.labels.otherFindings'), findings: leftover })
	return groups
}

/** How a round is named wherever it is shown.
 *
 * Mirrors round_heading() in citizens/services/report.py — the two must agree,
 * or the same round is called different things on screen and in the export.
 * That Python function reads its wording from citizens/services/report_text.py
 * keyed on the assembly's language (English "Round N", Italian "Turno N");
 * this reads the matching organizer.results.labels keys through t(), which
 * follows the UI's own current locale.
 *
 * The app manufactures its own redundancy here: both creation paths pre-fill
 * the title with "Session N" (before 0.7: "Round N"; English, regardless of
 * the assembly's language), so an organizer who edits it to "Session 1 -
 * design" would get "Session 1 — Session 1 - design" everywhere.
 */
/** The titles the app itself pre-fills, in every spelling it has used. */
const DEFAULT_TITLE_WORDS = ['session', 'round', 'sessione', 'turno']

export function roundHeading(position: number, title: string): string {
	const name = (title ?? '').trim()
	const defaultHeading = t('organizer.results.labels.round', { position })
	const lowered = name.toLowerCase()
	if (!name || DEFAULT_TITLE_WORDS.some((word) => lowered === `${word} ${position}`)) return defaultHeading
	const first = name.split(/\s+/)[0]?.replace(/[.:\-–—]+$/, '') ?? ''
	if (
		DEFAULT_TITLE_WORDS.some((word) => lowered.startsWith(`${word} ${position}`)) ||
		lowered.startsWith(defaultHeading.toLowerCase()) ||
		first === String(position)
	) {
		return name
	}
	return t('organizer.results.labels.roundTitled', { position, title: name })
}

/** The thing the Report tab closes and reopens, with its article: an
 * organized assembly, or a standalone Session (which is the container's
 * `kind`). Both spellings, so a sentence can start with it. Before 0.7 the
 * English said "session" for both and the Italian "assemblea" for both. */
export function kindNoun(kind: string | null | undefined): { thing: string; Thing: string } {
	const key = kind === 'session' ? 'session' : 'assembly'
	return { thing: t(`organizer.shell.kind.${key}`), Thing: t(`organizer.shell.kind.${key}Cap`) }
}
