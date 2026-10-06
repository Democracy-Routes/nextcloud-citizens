// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The organizer UI must not grow new English literals either (0.7).
 *
 * The recorder has had this guard since it was translated; the organizer SPA
 * followed in 0.7 (keys under organizer.* in frontend/src/i18n/organizer/).
 * Same heuristics as no-untranslated-recorder-strings.spec.ts, applied to
 * every component outside the recorder bundle: bare text nodes and string
 * literals inside moustaches in <template>, one English word is enough.
 *
 * Script-side text (toasts, confirm prompts, label maps) is covered by the
 * second test: a short list of patterns that only ever wrap user-facing
 * prose — toast('…'), confirm-label="…", title="…" — may not carry a literal.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const SRC = join(__dirname, '..', '..', 'frontend', 'src')
const ROOTS = [join(SRC, 'components'), join(SRC, 'App.vue')]

function vueFiles(path: string): string[] {
	if (!statSync(path).isDirectory()) return path.endsWith('.vue') ? [path] : []
	return readdirSync(path).flatMap((entry) => vueFiles(join(path, entry)))
}

function template(source: string): string {
	const match = source.match(/<template>([\s\S]*)<\/template>/)
	return match ? match[1] : ''
}

function script(source: string): string {
	const match = source.match(/<script[^>]*>([\s\S]*?)<\/script>/)
	return match ? match[1] : ''
}

function untranslatedPhrases(markup: string): string[] {
	const withoutComments = markup.replace(/<!--[\s\S]*?-->/g, ' ')
	const found: string[] = []
	for (const moustache of withoutComments.match(/\{\{[\s\S]*?\}\}/g) ?? []) {
		const displayed = moustache
			.replace(/(?:===|!==|==|!=)\s*(?:'[^']*'|"[^"]*")/g, ' ')
			.replace(/(?:'[^']*'|"[^"]*")\s*(?:===|!==|==|!=)/g, ' ')
			// t('key', { count: n }, n) — the key and the named arguments are not prose
			.replace(/\bt\(\s*(?:'[^']*'|"[^"]*"|`[^`]*`)/g, 't(')
		for (const literal of displayed.match(/'[^']*'|"[^"]*"/g) ?? []) {
			const text = literal.slice(1, -1)
			if (I18N_KEY.test(text) || CODE_TOKEN.test(text)) continue
			if (isProse(text)) found.push(text)
		}
	}
	const withoutTags = withoutComments
		.replace(/\{\{[\s\S]*?\}\}/g, ' ')
		.replace(/<(?:[^>"']|"[^"]*"|'[^']*')*>/g, '\n')
		.replace(/&[a-z]+;/gi, ' ')
	found.push(...withoutTags.split('\n').map((line) => line.trim()).filter(isProse))
	return found
}

/** Attributes that are read by a person: a literal there is untranslated text. */
const PROSE_ATTRIBUTES = /\s(?:placeholder|title|aria-label|alt|label|confirm-label|message|hint|empty-text)="([^"{][^"]*)"/g

function untranslatedAttributes(markup: string): string[] {
	const found: string[] = []
	for (const match of markup.replace(/<!--[\s\S]*?-->/g, ' ').matchAll(PROSE_ATTRIBUTES)) {
		const text = match[1]
		if (I18N_KEY.test(text) || CODE_TOKEN.test(text)) continue
		if (isProse(text)) found.push(text)
	}
	return found
}

/** Script calls that only ever carry user-facing text. */
const SCRIPT_PROSE_CALLS = /\b(?:toast|toastError|toastSuccess)\(\s*(?:'([^']*)'|"([^"]*)"|`([^`]*)`)/g

function untranslatedScriptLiterals(code: string): string[] {
	const found: string[] = []
	for (const match of code.matchAll(SCRIPT_PROSE_CALLS)) {
		const text = match[1] ?? match[2] ?? match[3] ?? ''
		if (I18N_KEY.test(text) || CODE_TOKEN.test(text)) continue
		if (isProse(text)) found.push(text)
	}
	return found
}

const I18N_KEY = /^[a-z0-9_]+(\.[a-z0-9_]+)+$/i
const CODE_TOKEN = /^[a-z0-9_-]+$/
const UNITS = new Set(['MB', 'kB', 'GB', 'ms', 'min', 'px', 'dB', 'Hz', 'kHz', 'QR', 'AI', 'API', 'PDF', 'CSV', 'JSON', 'URL', 'EN', 'IT'])

function isProse(text: string): boolean {
	const words = text.split(/\s+/).filter((word) => /[a-zA-Z]{2,}/.test(word))
	if (words.length === 0) return false
	if (words.every((word) => UNITS.has(word.replace(/[^a-zA-Z]/g, '')))) return false
	return true
}

describe('the organizer bundle', () => {
	const files = ROOTS.flatMap(vueFiles)

	it('has components to check', () => {
		expect(files.length).toBeGreaterThan(10)
	})

	it.each(files.map((file) => [file.split('/').slice(-1)[0], file]))(
		'%s renders no untranslated sentences',
		(_name, file) => {
			const source = readFileSync(file, 'utf8')
			const offenders = [
				...untranslatedPhrases(template(source)),
				...untranslatedAttributes(template(source)),
				...untranslatedScriptLiterals(script(source)),
			]
			expect(
				offenders,
				`untranslated text in ${file}:\n  ${offenders.join('\n  ')}\n` +
					'Move it into frontend/src/i18n/organizer/<area>.en.json and .it.json and use t().',
			).toEqual([])
		},
	)
})
