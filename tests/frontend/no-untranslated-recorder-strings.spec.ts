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
 * English left in the markup: bare text nodes, and string literals inside
 * moustache expressions.
 *
 * The literals matter as much as the text nodes. A ternary like
 * `{{ orchestrated ? 'The round has ended' : 'Time is up' }}` is invisible to a
 * scan that strips moustaches wholesale — which is exactly how six untranslated
 * strings survived on the citizens' recorder until a browser test walked into
 * one of them.
 *
 * Two words, not three. Three was chosen to keep "OK" and "ARMED" out of the
 * results, but it also let "Finish recording" and "Keep talking" through — and
 * those are buttons a citizen has to understand.
 */
function untranslatedPhrases(markup: string): string[] {
	const withoutComments = markup.replace(/<!--[\s\S]*?-->/g, ' ')

	const found: string[] = []
	for (const moustache of withoutComments.match(/\{\{[\s\S]*?\}\}/g) ?? []) {
		// a literal inside an expression is still text a person reads
		for (const literal of moustache.match(/'[^']{2,}'|"[^"]{2,}"/g) ?? []) {
			const text = literal.slice(1, -1)
			if (/^[a-z0-9_.]+$/i.test(text)) continue // an i18n key, not prose
			if (countWords(text) >= 2) found.push(text)
		}
	}

	const withoutTags = withoutComments
		.replace(/\{\{[\s\S]*?\}\}/g, ' ')
		// quoted attributes may themselves contain '>' (a Vue expression with a
		// cast or a comparison), so tags cannot be matched with [^>]+
		.replace(/<(?:[^>"']|"[^"]*"|'[^']*')*>/g, '\n')
	found.push(
		...withoutTags
			.split('\n')
			.map((line) => line.trim())
			.filter((line) => countWords(line) >= 2),
	)
	return found
}

function countWords(text: string): number {
	return text.split(/\s+/).filter((word) => /[a-zA-Z]{2,}/.test(word)).length
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
