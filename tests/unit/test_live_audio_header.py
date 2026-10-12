# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Seeding a caption decoder that starts in the middle of a recording.

Only the first chunk of a MediaRecorder segment carries the WebM header. A
backup phone promoted to live source, a failover to a sibling, a decoder
rebuilt after the idle reaper — all start on a later chunk, which ffmpeg
refuses ("Invalid data found when processing input", the 2026-10-11 field
log). The fix feeds the container header first; measured on real phone
chunks, Chrome cuts every chunk at a Cluster boundary, so header + later
chunk decodes cleanly without the first chunk's stale audio.
"""

import asyncio
import shutil
import subprocess

import pytest

from citizens.services import live_audio
from citizens.services.live_audio import EBML_MAGIC, WEBM_CLUSTER_ID, container_header


def test_webm_header_is_everything_before_the_first_cluster():
    header = EBML_MAGIC + b"\x42\x86\x81\x01" + b"\x18\x53\x80\x67\x01\xff\xff\xff\xff\xff\xff\xff"
    first_chunk = header + WEBM_CLUSTER_ID + b"\x01\x00\x00\x00\x00\x00\x00\x10audio-frames"
    assert container_header(first_chunk) == header


def test_a_container_without_clusters_is_sent_whole():
    # an iPhone's fragmented mp4: the first chunk IS the init segment
    mp4 = b"\x00\x00\x00\x1cftypiso5" + b"moov-and-first-fragment"
    assert container_header(mp4) == mp4
    # a WebM chunk whose Cluster id is missing (never seen; be safe, send all)
    assert container_header(EBML_MAGIC + b"no-cluster-here") == EBML_MAGIC + b"no-cluster-here"


def _webm_stream(path, seconds: int) -> bytes:
    """A real Opus-in-WebM stream, one Cluster per second, as a phone makes."""
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-c:a", "libopus", "-b:a", "24k", "-cluster_time_limit", "1000",
            "-f", "webm", str(path),
        ],
        check=True,
    )
    return path.read_bytes()


def _chunks_at_cluster_boundaries(stream: bytes, clusters_per_chunk: int) -> tuple[bytes, list[bytes]]:
    offsets = []
    start = 0
    while True:
        at = stream.find(WEBM_CLUSTER_ID, start)
        if at < 0:
            break
        offsets.append(at)
        start = at + 1
    header = stream[: offsets[0]]
    cuts = offsets[::clusters_per_chunk] + [len(stream)]
    return header, [stream[a:b] for a, b in zip(cuts, cuts[1:], strict=False)]


async def _decode(parts: list[bytes]) -> int:
    stream = live_audio.PcmStream("rec-seed")
    assert await stream.start()
    for part in parts:
        stream.feed(part)
    await stream.close()
    total = 0
    while True:
        pcm = await stream.read()
        if pcm is None:
            break
        total += len(pcm)
    return total


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_header_plus_a_later_chunk_decodes_and_the_later_chunk_alone_does_not(tmp_path):
    stream = _webm_stream(tmp_path / "phone.webm", seconds=24)
    header, chunks = _chunks_at_cluster_boundaries(stream, clusters_per_chunk=8)
    assert len(chunks) >= 3, "the stream must span several ten-second-style chunks"
    assert container_header(chunks[0]) == chunks[0], "a mid-stream chunk has no header to cut"
    assert container_header(header + chunks[0]) == header

    seeded = asyncio.run(_decode([header, chunks[2]]))
    orphan = asyncio.run(_decode([chunks[2]]))
    reference = asyncio.run(_decode([header + chunks[0]]))

    assert orphan == 0, "ffmpeg decoded a chunk with no container header"
    # about eight seconds of 16 kHz mono PCM, and nothing from chunk 0
    assert seeded > 0.8 * reference, f"seeded decode produced only {seeded} bytes"
    assert seeded < 1.5 * reference, "the seed leaked the first chunk's audio"
