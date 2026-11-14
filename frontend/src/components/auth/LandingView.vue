<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
/** The first screen of the standalone mode: what the software is, and the sign-in card. */
import { useI18n } from 'vue-i18n'
import { LANDING_LINKS } from '../../landing-links'
import type { Account, AuthConfig } from '../../types'
import LoginView from './LoginView.vue'

defineProps<{ config: AuthConfig }>()
const emit = defineEmits<{ 'signed-in': [account: Account] }>()
const { t } = useI18n()

const links = LANDING_LINKS
const iconUrl = '/img/app.svg'
const steps = ['record', 'analyse', 'review', 'polis'] as const
</script>

<template>
	<div class="cz-landing" data-test="landing-view">
		<div class="cz-landing__inner">
			<aside class="cz-landing__login">
				<LoginView :config="config" @signed-in="(account) => emit('signed-in', account)" />
			</aside>

			<div class="cz-landing__content">
				<header class="cz-landing__hero">
					<img :src="iconUrl" alt="" width="64" height="64" />
					<h1 data-test="landing-title">{{ t('organizer.shell.landing.hero.title') }}</h1>
					<p class="cz-landing__claim">{{ t('organizer.shell.landing.hero.claim') }}</p>
					<p>{{ t('organizer.shell.landing.hero.lead') }}</p>
				</header>

				<section>
					<h2>{{ t('organizer.shell.landing.how.title') }}</h2>
					<ol class="cz-landing__steps">
						<li v-for="(step, index) in steps" :key="step" class="cz-card" data-test="landing-step">
							<span class="cz-landing__num" aria-hidden="true">{{ index + 1 }}</span>
							<h3>{{ t(`organizer.shell.landing.how.${step}.title`) }}</h3>
							<p class="cz-muted">{{ t(`organizer.shell.landing.how.${step}.text`) }}</p>
						</li>
					</ol>
				</section>

				<section>
					<h2>{{ t('organizer.shell.landing.routes.title') }}</h2>
					<p>{{ t('organizer.shell.landing.routes.text') }}</p>
					<div class="cz-landing__tools">
						<div class="cz-card" data-test="landing-tool-citizens">
							<h3>{{ t('organizer.shell.landing.routes.citizens.title') }}</h3>
							<p class="cz-muted">{{ t('organizer.shell.landing.routes.citizens.text') }}</p>
							<a class="cz-btn" :href="links.CITIZENS_REPO_URL" target="_blank" rel="noopener">
								{{ t('organizer.shell.landing.open') }}
							</a>
						</div>
						<div class="cz-card" data-test="landing-tool-polis">
							<h3>{{ t('organizer.shell.landing.routes.polis.title') }}</h3>
							<p class="cz-muted">{{ t('organizer.shell.landing.routes.polis.text') }}</p>
							<a class="cz-btn" :href="links.POLIS_INSTANCE_URL" target="_blank" rel="noopener">
								{{ t('organizer.shell.landing.open') }}
							</a>
							<a class="cz-landing__repo" :href="links.POLIS_REPO_URL" target="_blank" rel="noopener">
								{{ t('organizer.shell.landing.links.polisRepo') }}
							</a>
						</div>
					</div>
				</section>

				<footer class="cz-landing__links">
					<nav>
						<a :href="links.DEMOCRACY_ROUTES_URL" target="_blank" rel="noopener">{{ t('organizer.shell.landing.links.site') }}</a>
						<a :href="links.CITIZENS_REPO_URL" target="_blank" rel="noopener">{{ t('organizer.shell.landing.links.citizensRepo') }}</a>
						<a :href="links.POLIS_REPO_URL" target="_blank" rel="noopener">{{ t('organizer.shell.landing.links.polisRepo') }}</a>
						<a :href="links.LICENSE_URL" target="_blank" rel="noopener">{{ t('organizer.shell.landing.links.license') }}</a>
					</nav>
					<p class="cz-muted">{{ links.POWERED_BY }}</p>
				</footer>
			</div>
		</div>
	</div>
</template>

<style scoped>
.cz-landing {
	min-height: 100vh;
	background: #f5f7fa;
	padding: 24px 16px 48px;
	box-sizing: border-box;
}
.cz-landing__inner {
	max-width: 1100px;
	margin: 0 auto;
	display: flex;
	flex-direction: column;
	gap: 32px;
}
.cz-landing__login :deep(.cz-card) {
	margin: 0 auto !important;
}
.cz-landing__hero img {
	display: block;
	margin-bottom: 8px;
}
.cz-landing__hero h1 {
	margin: 0 0 4px;
	font-size: 2.2rem;
}
.cz-landing__claim {
	font-size: 1.2rem;
	font-weight: 600;
	margin: 0 0 12px;
}
.cz-landing__content section {
	margin-top: 32px;
}
.cz-landing__steps {
	list-style: none;
	margin: 0;
	padding: 0;
	display: grid;
	grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
	gap: 14px;
}
.cz-landing__steps li,
.cz-landing__tools .cz-card {
	padding: 16px;
}
.cz-landing__steps h3,
.cz-landing__tools h3 {
	margin: 6px 0;
}
.cz-landing__num {
	display: inline-flex;
	width: 28px;
	height: 28px;
	border-radius: 50%;
	align-items: center;
	justify-content: center;
	background: var(--color-primary-element, #0082c9);
	color: var(--color-primary-element-text, #fff);
	font-weight: 700;
}
.cz-landing__tools {
	display: grid;
	grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
	gap: 14px;
	margin-top: 14px;
}
.cz-landing__repo {
	margin-left: 12px;
}
.cz-landing__links {
	margin-top: 40px;
	padding-top: 16px;
	border-top: 1px solid rgba(0, 0, 0, 0.12);
}
.cz-landing__links nav {
	display: flex;
	flex-wrap: wrap;
	gap: 8px 20px;
}
@media (min-width: 900px) {
	.cz-landing {
		padding-top: 48px;
	}
	.cz-landing__inner {
		flex-direction: row;
		align-items: flex-start;
		gap: 48px;
	}
	.cz-landing__content {
		order: 1;
		flex: 0 0 60%;
		max-width: 60%;
	}
	.cz-landing__login {
		order: 2;
		flex: 1 1 0;
		position: sticky;
		top: 24px;
	}
}
</style>
