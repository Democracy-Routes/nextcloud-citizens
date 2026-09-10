# Recording reliability

Audio is the primary record. Captions, transcription and analysis are not a
substitute for it. This implementation reduces recoverable failure modes; it
cannot guarantee capture through a dead battery, a killed browser, a lost
microphone, failing hardware, or erased browser storage.

## What “synchronized” means

The phone first commits each original MediaRecorder chunk to IndexedDB. Upload
acknowledgements do not delete it. Normal chunks use the existing upload route;
oversized chunks, or uploads rejected with HTTP 413, use 1 MiB parts. The server
stores immutable part metadata and checksums, flushes the bytes and directory
entries, and commits its receipt before acknowledging them. A retry asks which
parts are present and resumes. Finalization verifies the original chunk's size
and checksum without changing its sequence number or bytes.

After assembly, the server stores a fingerprint of the ordered original chunks:
SHA-256 of UTF-8 lines `sequence:size:sha256\n`. The phone compares that
fingerprint, byte count and chunk count against its own complete local inventory.
It also requires validated, available server audio. Only then does it mark the
recording verified and eligible for normal local cleanup. A salvaged prefix, a
gap, an unavailable file or an old unverified completion flag is insufficient.
Older recordings can be verified from their existing server manifest; without
that evidence their local audio remains untouched.

## Recovery behavior

- Network errors, rate limits and server failures back off and retry. Microphone
  capture continues locally while an upload is unavailable or rejected.
- A permanent rejection stops automatic upload retries and asks for attention;
  it does not silently stop an active microphone.
- Expired or revoked sessions do not hide local audio. The recovery screen offers
  a download, keeping the copy, or explicitly confirming its deletion. A fresh
  QR for the same assembly and table resumes the original recording. Unknown
  legacy ownership is not guessed, and server authorization is unchanged.
- Failed local writes retain their blobs in memory for retry or download while
  the page remains alive. A storage warning needs immediate attention: that
  memory is **not** crash-safe. Missing audio is never concealed by declaring a
  shorter recording complete.
- Unfinished server parts have no automatic expiry. They are reclaimed after
  verified assembly, or as part of explicitly requested audio deletion. They
  consume disk until then; monitor capacity.
- Recovery heartbeats count the original assembly's local recordings only.
  Unreadable storage or unknown ownership is reported as unknown, not zero.

## Before using this build for an assembly

1. Back up the persistent database and audio volume before upgrading. Migration
   `0020` adds nullable verification fields and the part-receipt table; it does
   not rewrite existing audio. Deploy backend and rebuilt recorder assets together.
2. Check the actual Nextcloud/proxy path permits the new part/status/finalize
   routes and binary bodies of at least 1 MiB. Check storage supports file and
   directory fsync. SQLite now uses `synchronous=FULL` for durable receipts.
3. Run a rehearsal over the venue's HTTPS connection on the actual Android and
   iPhone devices: capture, disconnect Wi-Fi, reconnect, finish, play the server
   export, then test reload recovery and a fresh QR after session expiry.
4. Keep the recorder page open and the phone powered. React immediately to
   microphone or storage warnings. Use an independent backup recorder for an
   irreplaceable assembly; a second tab on the same phone is not independent.
5. Before clearing devices, verify the server recording and preserve a backed-up
   export. Starting a download is not proof the file was saved or is playable.

Automated tests use temporary storage and fake microphones. They exercise bytes,
checksums, interrupted transfers, browser reloads, server restarts, session
revocation, concurrent tables and cleanup. They do not certify physical power-loss
durability, Safari background behavior, microphone quality, or the production
reverse-proxy configuration. No production deployment is part of this change.
