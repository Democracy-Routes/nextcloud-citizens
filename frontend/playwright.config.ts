import { defineConfig, devices } from '@playwright/test'

// Firefox: Chromium 151's --use-fake-device-for-media-capture no longer
// provides a fake microphone on this host; Firefox's fake-stream prefs do.
export default defineConfig({
	testDir: '../tests/browser',
	timeout: 180_000,
	retries: 0,
	workers: 1,
	use: {
		baseURL: process.env.CITIZENS_TEST_URL ?? 'http://127.0.0.1:23100',
		...devices['Desktop Firefox'],
		launchOptions: {
			firefoxUserPrefs: {
				'media.navigator.streams.fake': true,
				'media.navigator.permission.disabled': true,
			},
		},
	},
	projects: [{ name: 'firefox', use: { browserName: 'firefox' } }],
})
