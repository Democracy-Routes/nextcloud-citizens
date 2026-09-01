// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

// Specs live in ../tests/frontend so the repo keeps one tests/ tree
// (unit, integration, browser, frontend). That is above this config's root,
// so Vite has to be told it may serve files from there.
export default defineConfig({
	plugins: [vue()],
	server: { fs: { allow: ['..'] } },
	test: {
		environment: 'happy-dom',
		include: ['../tests/frontend/**/*.spec.ts'],
	},
})
