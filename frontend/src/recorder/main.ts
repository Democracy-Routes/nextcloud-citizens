// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
import { createApp } from 'vue'
import { i18n, setLocale } from '../i18n'
import RecorderApp from './RecorderApp.vue'
import './style.css'

// Best guess until the session says which language the ROOM is using. The
// invite token lives in the URL fragment and never reaches the server, so the
// page cannot be rendered in the right language server-side; RecorderApp calls
// setLocale again with the assembly's language as soon as it joins.
setLocale(navigator.language)

const root = document.getElementById('recorder-app') ?? document.body
root.innerHTML = ''
createApp(RecorderApp).use(i18n).mount(root)
