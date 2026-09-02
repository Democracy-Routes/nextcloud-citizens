<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { JoinResult } from '../api'
import { RecorderEngine } from '../engine'
import { downloadBlob } from '../../download'
import { idb, type StoredRecording } from '../idb'

const props = defineProps<{ session: JoinResult; recording: StoredRecording }>()
const emit = defineEmits<{ done: [] }>()

const { t } = useI18n()

const engine = new RecorderEngine()
const state = engine.state

const pending = computed(() => state.localChunks - state.ackedChunks)
const confirmDelete = ref(false)
const downloadNote = ref('')

onMounted(() => {
	void engine.resumeSync(props.session.session_token, props.recording)
})

// the server definitively lost this recording (deleted assembly / reset):
// the audio still exists locally — let people save it to the phone…
async function downloadAudio(): Promise<void> {
	const chunks = await idb.chunksFor(props.recording.recordingId)
	chunks.sort((a, b) => a.seq - b.seq)
	const mime = props.recording.mimeType || 'audio/webm'
	const ext = mime.includes('ogg') ? 'ogg' : mime.includes('mp4') ? 'm4a' : 'webm'
	const blob = new Blob(chunks.map((c) => c.blob), { type: mime.split(';')[0] })
	downloadBlob(blob, `citizens-table-${props.session.table_number}-recovered.${ext}`)
	downloadNote.value = 'Audio file saved to this phone’s downloads.'
}

// …and delete the local copy only behind an explicit confirmation
async function deleteLocal(): Promise<void> {
	await idb.deleteChunksFor(props.recording.recordingId)
	await idb.deleteRecording(props.recording.recordingId)
	emit('done')
}
</script>

<template>
	<div class="rc-fill">
		<div class="rc-header">
			<span class="rc-table-badge">TABLE {{ session.table_number }}</span>
		</div>

		<div class="rc-scroll">
		<div class="rc-card">
			<h2>{{ t('recorder.recovery.title') }}</h2>
			<p class="rc-muted">
				{{ t('recorder.recovery.intro') }}
			</p>
			<div class="rc-status-row">
				<span>{{ t('recorder.recovery.chunks') }}</span><span>{{ state.localChunks }}</span>
			</div>
			<div class="rc-status-row">
				<span>{{ t('recorder.recovery.awaitingUpload') }}</span>
				<span :class="pending > 0 ? 'rc-warn' : 'rc-ok'">{{ pending }}</span>
			</div>
			<div class="rc-status-row">
				<span>Server</span><span>{{ state.serverState || '—' }}</span>
			</div>
		</div>

		<template v-if="state.phase === 'syncing'">
			<div v-if="!state.uploadOnline" class="rc-note">
				{{ t('recorder.recovery.waiting') }}
				<button class="rc-btn" style="margin-top: 10px" @click="engine.retryNow()">{{ t('recorder.common.retryNow') }}</button>
			</div>
			<p v-else class="rc-muted rc-center">Synchronizing…</p>
		</template>

		<template v-else-if="state.phase === 'done'">
			<div class="rc-note">✅ {{ t('recorder.recovery.done') }}</div>
			<button class="rc-btn rc-primary" @click="emit('done')">Continue</button>
		</template>

		<template v-else-if="state.phase === 'failed'">
			<template v-if="state.errorKind === 'gone'">
				<div class="rc-alert">
					{{ t('recorder.recovery.gone') }}
				</div>
				<p v-if="downloadNote" class="rc-note">{{ downloadNote }}</p>
				<button class="rc-btn rc-primary" @click="downloadAudio">{{ t('recorder.recovery.download') }}</button>
				<template v-if="confirmDelete">
					<div class="rc-note" style="margin-bottom: 8px">
						{{ t('recorder.recovery.confirmDelete') }}
					</div>
					<button class="rc-btn rc-record" @click="deleteLocal">{{ t('recorder.recovery.confirmDeleteYes') }}</button>
					<button class="rc-btn rc-subtle" @click="confirmDelete = false">{{ t('recorder.recovery.keep') }}</button>
				</template>
				<button v-else class="rc-btn" @click="confirmDelete = true">{{ t('recorder.recovery.delete') }}</button>
				<button class="rc-btn rc-subtle" @click="emit('done')">{{ t('recorder.recovery.skip') }}</button>
			</template>
			<template v-else>
				<div class="rc-alert">
					{{ t('recorder.recovery.failed') }} {{ state.error }}<br />
					{{ t('recorder.recovery.failedHint') }}
				</div>
				<button class="rc-btn" @click="engine.retryNow()">{{ t('recorder.common.tryAgain') }}</button>
				<button class="rc-btn rc-subtle" @click="emit('done')">{{ t('recorder.recovery.skip') }}</button>
			</template>
		</template>
		</div>
	</div>
</template>
