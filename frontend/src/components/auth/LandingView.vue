<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
/** The first screen of the standalone mode: the sign-in card and the way
 * back to the project site. What Democracy Routes is lives on
 * democracyroutes.com, not here. */
import { useI18n } from 'vue-i18n'
import { LANDING_LINKS } from '../../landing-links'
import type { Account, AuthConfig } from '../../types'
import LoginView from './LoginView.vue'

defineProps<{ config: AuthConfig }>()
const emit = defineEmits<{ 'signed-in': [account: Account] }>()
const { t } = useI18n()

const links = LANDING_LINKS
const iconUrl = '/img/app.svg'
</script>

<template>
	<div class="cz-landing" data-test="landing-view">
		<div class="cz-landing__inner">
			<header class="cz-landing__hero">
				<img :src="iconUrl" alt="" width="56" height="56" />
				<h1 data-test="landing-title">{{ t('organizer.shell.landing.title') }}</h1>
				<p class="cz-landing__claim">{{ t('organizer.shell.landing.claim') }}</p>
				<p class="cz-muted">{{ t('organizer.shell.landing.lead') }}</p>
			</header>

			<LoginView :config="config" @signed-in="(account) => emit('signed-in', account)" />

			<footer class="cz-landing__links">
				<a :href="links.DEMOCRACY_ROUTES_URL" data-test="landing-back" rel="noopener">
					← {{ t('organizer.shell.landing.back') }}
				</a>
				<p class="cz-muted">{{ links.POWERED_BY }}</p>
			</footer>
		</div>
	</div>
</template>

<style scoped>
.cz-landing {
	min-height: 100vh;
	background: #f5f7fa;
	padding: 48px 16px;
	box-sizing: border-box;
}
.cz-landing__inner {
	max-width: 420px;
	margin: 0 auto;
}
.cz-landing__hero {
	text-align: center;
	margin-bottom: 20px;
}
.cz-landing__hero img {
	display: block;
	margin: 0 auto 8px;
}
.cz-landing__hero h1 {
	margin: 0 0 4px;
	font-size: 2rem;
}
.cz-landing__claim {
	font-size: 1.05rem;
	font-weight: 600;
	margin: 0 0 8px;
}
.cz-landing :deep(.cz-card) {
	margin: 0 auto !important;
}
.cz-landing__links {
	text-align: center;
	margin-top: 20px;
}
.cz-landing__links p {
	margin-top: 10px;
	font-size: 0.9rem;
}
</style>
