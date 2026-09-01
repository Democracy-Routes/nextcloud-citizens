// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { defineComponent } from 'vue'

/** The runner itself: a DOM, Vue SFC mounting, and the repo's path layout. */
describe('the frontend test harness', () => {
	it('mounts a component and renders it', () => {
		const Hello = defineComponent({ template: '<p class="x">hello</p>' })
		expect(mount(Hello).find('.x').text()).toBe('hello')
	})

	it('has a DOM', () => {
		expect(typeof document).toBe('object')
	})
})
