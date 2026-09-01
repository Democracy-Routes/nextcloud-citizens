// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The citizens' recorder must not grow new English literals.
 *
 * Translating it once is easy; keeping it translated is the hard part, and the
 * failure is silent — a new button reads fine to whoever added it and is
 * English on every phone in the room. This is the version that cannot be
 * forgotten, in the spirit of the repo's other guard tests.
 *
 * It looks only at the recorder bundle, which is the citizen-facing half. The
 * organizer SPA is translated in a later step and can be added to ROOTS then.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const ROOTS = [join(__dirname, '..', '..', 'frontend', 'src', 'recorder')]

function vueFiles(directory: string): string[] {
	return readdirSync(directory).flatMap((entry) => {
		const path = join(directory, entry)
		if (statSync(path).isDirectory()) return vueFiles(path)
		return path.endsWith('.vue') ? [path] : []
	})
}

/** The <template> block only — script comments and CSS are not user-visible. */
function template(source: string): string {
	const match = source.match(/<template>([\s\S]*)<\/template>/)
	return match ? match[1] : ''
}

/**
 * Text nodes of three or more words that are not inside a moustache.
 * Three, not one, so that "OK", "ARMED" and unit suffixes do not swamp the
 * signal — a full sentence is what actually reads as untranslated.
 */
function untranslatedPhrases(markup: string): string[] {
	const withoutTags = markup
		.replace(/<!--[\s\S]*?-->/g, ' ')
		.replace(/\{\{[\s\S]*?\}\}/g, ' ')
		// quoted attributes may themselves contain '>' (a Vue expression with a
		// cast or a comparison), so tags cannot be matched with [^>]+
		.replace(/<(?:[^>"']|"[^"]*"|'[^']*')*>/g, '\n')
	return withoutTags
		.split('\n')
		.map((line) => line.trim())
		.filter((line) => line.split(/\s+/).filter((word) => /[a-zA-Z]{2,}/.test(word)).length >= 3)
}

describe('the recorder bundle', () => {
	const files = ROOTS.flatMap(vueFiles)

	it('has components to check', () => {
		expect(files.length).toBeGreaterThan(0)
	})

	it.each(files.map((file) => [file.split('/').slice(-1)[0], file]))(
		'%s renders no untranslated sentences',
		(_name, file) => {
			const offenders = untranslatedPhrases(template(readFileSync(file, 'utf8')))
			expect(
				offenders,
				`untranslated text in ${file}:\n  ${offenders.join('\n  ')}\n` +
					'Move it into frontend/src/i18n/en.json and it.json and use $t().',
			).toEqual([])
		},
	)
})
