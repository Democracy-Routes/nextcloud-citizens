// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
import { createApp } from 'vue'
import { i18n, setLocale } from './i18n'
import App from './App.vue'
import './style.css'

function mount(): void {
	const content = document.getElementById('content') ?? document.body
	const root = document.createElement('div')
	root.id = 'citizens-app'
	content.innerHTML = ''
	content.appendChild(root)
	// Nextcloud sets the document language from the user's own preference
	setLocale(document.documentElement.lang)
	createApp(App).use(i18n).mount(root)
}

if (document.readyState === 'loading') {
	document.addEventListener('DOMContentLoaded', mount)
} else {
	mount()
}
