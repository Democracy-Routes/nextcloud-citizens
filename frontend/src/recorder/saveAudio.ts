// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/** Saving a table's local audio to the phone, and saying what happened.
 *
 * Two screens offer this — the recovery screen and the failed-sync screen —
 * and both used to call the bare anchor download and then report "Download
 * started" whatever had happened. On an iPhone what had happened was a
 * navigation away from the page (see download.ts). The outcome now comes
 * back to the screen, and every attempt is written to the device log, so the
 * next time a phone shows a strange screen the log says what was tapped and
 * what the browser did with it.
 */

import { canShareFiles, saveBlob, type SaveOutcome } from '../download'
import { clientLog, ship } from './logger'

export interface LocalAudio {
	blob: Blob
	filename: string
	chunks: number
}

export type SaveResult = SaveOutcome | 'failed'

/** The extension a file of this MIME type should carry; the same rule for
 * every caller, so a recovered file and a failed-sync file of the same
 * recording do not end up with different names. */
export function audioExtension(mime: string): string {
	if (mime.includes('mp4')) return 'm4a'
	if (mime.includes('ogg')) return 'ogg'
	return 'webm'
}

/** Save prepared audio and log the attempt. Never throws: the screen shows
 * the result, and a failure to save must not take the recorder with it. */
export async function saveLocalAudio(audio: LocalAudio): Promise<SaveResult> {
	const file = new File([audio.blob], audio.filename, { type: audio.blob.type })
	clientLog('info', 'audio_save_requested', {
		chunks: audio.chunks,
		bytes: audio.blob.size,
		share: canShareFiles(file),
	})
	try {
		const outcome = await saveBlob(audio.blob, audio.filename)
		clientLog('info', 'audio_save_finished', { outcome })
		return outcome
	} catch (error) {
		clientLog('error', 'audio_save_failed', {
			name: error instanceof Error ? error.name : '',
			message: String(error).slice(0, 160),
		})
		return 'failed'
	} finally {
		void ship()
	}
}

/** The catalogue key for what the screen should say afterwards; empty when
 * the person dismissed the share sheet, which needs no comment. */
export function saveNoteKey(result: SaveResult): string {
	switch (result) {
		case 'shared':
			return 'recorder.recovery.saved'
		case 'downloaded':
			return 'recorder.recovery.downloadStarted'
		case 'failed':
			return 'recorder.recovery.saveFailed'
		default:
			return ''
	}
}
