# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The parts of the remote load test that do not need a server.

tests/load/load_i_remote_tables.py drives ten virtual phones against another
organisation's production Nextcloud. Almost everything it does needs that
server — but the arithmetic does not, and the arithmetic is where a mistake
would either waste a scheduled window with those admins or, worse, upload the
wrong audio to the wrong assembly. Link parsing, the chunk schedule across an
interruption, the manifest the server will publish, and every refusal are all
pure functions, and they are what this covers.
"""

import hashlib
import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
PROXY = "https://cloud.example.org/index.php/apps/app_api/proxy/citizens"
TOKEN = "HVGMPlsVX0q1uvwl8fbgmTHUEMFWg5NS5DHVHwlnCvw"


def _module():
    spec = importlib.util.spec_from_file_location(
        "load_i", ROOT / "tests" / "load" / "load_i_remote_tables.py")
    module = importlib.util.module_from_spec(spec)
    # @dataclass resolves its annotations through sys.modules[cls.__module__],
    # so a module loaded by path has to be registered before it is executed
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


load_i = _module()


# ------------------------------------------------------------------- links


@pytest.mark.parametrize(
    "link, base",
    [
        (f"{PROXY}/recorder.html#/join/{TOKEN}", PROXY),
        # HaRP serves the same app somewhere else entirely
        (f"https://cloud.example.org/exapps/citizens/recorder.html#/join/{TOKEN}",
         "https://cloud.example.org/exapps/citizens"),
        (f"{PROXY}/recorder/#/join/{TOKEN}", PROXY),
        (f"{PROXY}/recorder#/join/{TOKEN}", PROXY),
        (f"http://localhost:8080/index.php/apps/app_api/proxy/citizens/recorder.html#/join/{TOKEN}",
         "http://localhost:8080/index.php/apps/app_api/proxy/citizens"),
    ],
)
def test_a_join_link_yields_the_api_base_and_the_token(link, base):
    """The base is never assumed: a HaRP deployment's path is not the proxy's."""
    parsed = load_i.parse_link(link)
    assert parsed.base == base
    assert parsed.token == TOKEN


@pytest.mark.parametrize(
    "link",
    [
        "",
        f"{PROXY}/recorder.html",  # no fragment
        f"{PROXY}/recorder.html#/report",  # the wrong screen
        f"{PROXY}/recorder.html#/join/short",  # not a token
        f"{PROXY}/recorder.html#/join/{TOKEN}!!",  # nor that
        f"{PROXY}/something-else.html#/join/{TOKEN}",
        f"ftp://cloud.example.org/x/recorder.html#/join/{TOKEN}",
    ],
)
def test_something_that_is_not_a_join_link_is_refused(link):
    with pytest.raises(ValueError):
        load_i.parse_link(link)


def test_links_from_two_servers_are_refused(tmp_path):
    """Ten links, two hosts: somebody pasted from two emails, and half the run
    would land on the wrong instance."""
    listing = tmp_path / "links.txt"
    listing.write_text(
        f"{PROXY}/recorder.html#/join/{TOKEN}\n"
        f"https://other.example.net/index.php/apps/app_api/proxy/citizens"
        f"/recorder.html#/join/{TOKEN[:-1]}b\n"
    )

    with pytest.raises(SystemExit, match="different servers"):
        load_i.read_links([str(listing)], [], [])


def test_the_same_link_twice_is_used_once(tmp_path):
    listing = tmp_path / "links.txt"
    listing.write_text(f"{PROXY}/recorder.html#/join/{TOKEN}\n" * 3
                       + "# a comment\n\n")

    assert len(load_i.read_links([str(listing)], [], [])) == 1


def test_a_token_is_never_printed_whole():
    """These are credentials for somebody else's assembly, and the report is
    something we paste into an email."""
    masked = load_i.mask(TOKEN)

    assert TOKEN not in masked
    assert masked.startswith(TOKEN[:4])
    assert "(43)" in masked


# ------------------------------------------------------------------- audio windows


def test_windows_are_far_apart_when_there_is_enough_audio():
    """165 minutes of test recordings, ten tables of eight minutes: no
    repetition needed, and no two tables hear the same window."""
    copies, stride = load_i.window_plan(165 * 60, tables=10, minutes=8)

    assert copies == 1
    assert stride * 9 + 8 * 60 <= 165 * 60 + 1
    starts = [round(index * stride) for index in range(10)]
    assert len(set(starts)) == 10


def test_the_material_is_repeated_only_as_much_as_it_has_to_be():
    copies, stride = load_i.window_plan(165 * 60, tables=10, minutes=40)

    assert copies == 3  # 400 minutes wanted out of 165
    assert stride > 40 * 60 / 10  # windows still walk forward
    assert 9 * stride + 40 * 60 <= 165 * 60 * copies + 1


def test_a_window_longer_than_the_material_is_refused():
    """It would loop inside one table's own recording: the same voices saying
    the same thing twice, in one transcript."""
    with pytest.raises(SystemExit, match="cannot cover"):
        load_i.window_plan(60.0, tables=10, minutes=40)


def test_material_that_would_have_to_repeat_too_often_is_refused():
    """Ten tables all hearing the same twenty minutes is a load test with no
    analysis worth reading."""
    with pytest.raises(SystemExit, match="repeat"):
        load_i.window_plan(20 * 60, tables=10, minutes=15)


# ------------------------------------------------------------------- the schedule


def test_a_plain_table_sends_one_segment_on_a_ten_second_grid():
    """A MediaRecorder with a ten-second timeslice delivers its first blob at
    +10 s and a short one when it stops — not a chunk at zero."""
    plan = load_i.plan_chunks(minutes=8)

    assert plan.segments == 1
    assert len(plan.specs) == 48
    assert plan.specs[0].due == 10
    assert plan.specs[-1].due == 480
    assert [spec.seq for spec in plan.specs] == list(range(48))
    assert {spec.segment for spec in plan.specs} == {0}
    assert sum(plan.segment_seconds) == pytest.approx(480)


def test_an_interrupted_table_continues_the_sequence_in_the_next_segment():
    """The whole point of 0.6.2: one recording, two MediaRecorder sessions. The
    gap is in time, not in the numbering — so /complete reports no missing
    sequences, and the server groups the chunks by segment to remux them."""
    plan = load_i.plan_chunks(minutes=8, interrupt_at=195, gap=45)

    assert plan.segments == 2
    assert [spec.seq for spec in plan.specs] == list(range(len(plan.specs)))
    first = [spec for spec in plan.specs if spec.segment == 0]
    second = [spec for spec in plan.specs if spec.segment == 1]
    assert first[-1].due == 195, "segment 0 ends with the flush of the dead session"
    assert second[0].seq == first[-1].seq + 1, "the sequence does not restart"
    assert second[0].due == 195 + 45 + 10, "the new session's first blob is 10 s in"
    assert plan.segment_seconds == [195, 480 - 240]
    assert sum(plan.segment_seconds) == pytest.approx(480 - 45)
    # each segment's pieces are numbered from zero: they are separate files
    assert [spec.piece for spec in second] == list(range(len(second)))


def test_an_interruption_the_server_would_call_a_dead_phone_is_refused():
    """Past STALLED_DEVICE_SECONDS the server releases the table to a
    replacement, which is a different test with a different verdict."""
    with pytest.raises(ValueError, match="outlives the server"):
        load_i.plan_chunks(minutes=8, interrupt_at=195, gap=125)


def test_an_interruption_outside_the_round_is_refused():
    with pytest.raises(ValueError, match="inside the round"):
        load_i.plan_chunks(minutes=8, interrupt_at=600, gap=45)


# ------------------------------------------------------------------- bytes


def test_byte_slices_cover_the_file_exactly_and_none_is_empty(tmp_path):
    """Chunk 0 carries the container header and the rest continue it, so the
    slices have to be the whole file, in order, with nothing dropped."""
    path = tmp_path / "window.webm"
    path.write_bytes(bytes(range(256)) * 41)  # 10496 bytes, divides unevenly by 48

    pieces = load_i.slice_pieces(path, 48)

    assert sum(piece.length for piece in pieces) == path.stat().st_size
    assert all(piece.length > 0 for piece in pieces)
    assert pieces[0].offset == 0
    for earlier, later in zip(pieces, pieces[1:], strict=False):
        assert later.offset == earlier.offset + earlier.length
    data = path.read_bytes()
    assert pieces[3].sha256 == hashlib.sha256(
        data[pieces[3].offset:pieces[3].offset + pieces[3].length]).hexdigest()


def test_the_manifest_we_expect_is_the_one_the_server_builds():
    """Two independent implementations of the same receipt.

    citizens/services/audio.py, after assembling:
        for chunk in chunks:
            manifest.update(f"{seq}:{size}:{sha}\\n".encode())
    If that formula ever changes, this fails here rather than in the middle of
    somebody else's rehearsal, where it would read as "the server holds
    different bytes".
    """
    pieces = [load_i.Piece(offset=0, length=11, sha256="aa"),
              load_i.Piece(offset=11, length=22, sha256="bb"),
              load_i.Piece(offset=33, length=7, sha256="cc")]
    server = hashlib.sha256()
    for seq, piece in enumerate(pieces):
        server.update(f"{seq}:{piece.length}:{piece.sha256}\n".encode())

    assert load_i.manifest_of(pieces) == (server.hexdigest(), 40)


# ------------------------------------------------------------------- the version gate


@pytest.mark.parametrize(
    "declared, accepted",
    [("0.6.2", True), ("0.7.0", True), ("1.0.0", True),
     ("0.6.1", False), ("0.6.1-beta.2", False), ("0.5.9", False), ("", False), ("nonsense", False)],
)
def test_the_version_gate_knows_which_builds_understand_segments(declared, accepted):
    numbers = load_i.version_tuple(declared)
    assert (numbers is not None and numbers >= load_i.SEGMENT_VERSION) is accepted


# ------------------------------------------------------------------- failures


def test_the_failure_taxonomy_names_what_went_wrong():
    """"it failed" is not a measurement: a timeout, a reset connection and a
    500 say different things about a server under load."""
    import http.client
    import socket
    import ssl

    assert load_i.classify(TimeoutError()) == "timeout"  # socket.timeout since 3.10
    assert load_i.classify(ConnectionResetError()) == "conn_reset"
    assert load_i.classify(http.client.RemoteDisconnected()) == "conn_closed"
    assert load_i.classify(ssl.SSLError()) == "tls"
    assert load_i.classify(socket.gaierror()) == "dns"


def test_percentiles_of_one_and_of_many():
    metrics = load_i.Metrics()
    metrics.record("chunk", load_i.Reply(200, {}, 0.5))
    assert metrics.percentiles("chunk") == (0.5, 0.5, 0.5)

    for seconds in range(1, 101):
        metrics.record("status", load_i.Reply(200, {}, seconds / 100))
    median, p95, worst = metrics.percentiles("status")
    assert median == pytest.approx(0.505, abs=0.01)
    assert p95 == pytest.approx(0.96, abs=0.02)
    assert worst == pytest.approx(1.0)


def test_an_outcome_is_counted_as_what_it_was():
    metrics = load_i.Metrics()
    metrics.record("chunk", load_i.Reply(200, {}, 0.1))
    metrics.record("chunk", load_i.Reply(500, {"detail": "boom"}, 0.2))
    metrics.record("chunk", load_i.Reply(409, {"detail": "no"}, 0.1))
    metrics.record("chunk", load_i.Reply(0, None, 30.0, "timeout"))

    assert metrics.outcomes["chunk"] == {"ok": 1, "5xx": 1, "409": 1, "timeout": 1}
    # a 4xx is our fault, not the server struggling: it is not a "fault" line
    assert [entry[2] for entry in metrics.faults] == ["5xx", "timeout"]


def test_the_breaker_stops_a_run_that_is_hurting_the_server():
    breaker = load_i.Breaker(server_errors=3, consecutive_slow=2, slow_seconds=30.0)
    assert not breaker.tripped()
    for _ in range(3):
        breaker.note(load_i.Reply(503, {}, 0.2))
    assert "server errors" in breaker.tripped()

    slow = load_i.Breaker(server_errors=99, consecutive_slow=2, slow_seconds=30.0)
    slow.note(load_i.Reply(200, {}, 31.0))
    slow.note(load_i.Reply(200, {}, 0.1))  # the streak breaks
    slow.note(load_i.Reply(200, {}, 31.0))
    slow.note(load_i.Reply(200, {}, 31.0))
    assert "in a row slower" in slow.tripped()


# ------------------------------------------------------------------- the verdict


def _run(**overrides):
    run = {
        "base": PROXY, "version": "0.6.2", "our_ip": "198.51.100.7",
        "assembly": "Datacenter (test8minuti)", "tables": 2, "minutes": 8.0,
        "interrupted": [1], "gap": 45.0, "audio": "real speech",
        "started_utc": "2026-09-30 10:00:00", "elapsed": 500.0, "aborted": "",
        "per_table": [
            {"number": 1, "sent": 44, "planned": 44, "megabytes": 4.2, "segments": 2,
             "state": "AUDIO_READY", "server_seconds": 435.0, "expected_seconds": 435.0,
             "manifest": "match", "captions": [(True, "")], "notes": [],
             "recording_id": "r1", "duplicates": 0, "max_backlog": 1},
            {"number": 2, "sent": 48, "planned": 48, "megabytes": 4.6, "segments": 1,
             "state": "TRANSCRIBED", "server_seconds": 480.0, "expected_seconds": 480.0,
             "manifest": "match", "captions": [(True, "")], "notes": [],
             "recording_id": "r2", "duplicates": 0, "max_backlog": 1},
        ],
        "outcomes": {"chunk": {"ok": 92}}, "latency": {"chunk": (0.1, 0.3, 0.9)},
        "worst_minute": (3, {"n": 40, "worst": 0.9}), "faults": [],
    }
    run.update(overrides)
    return run


def test_a_clean_run_passes_and_says_the_segments_were_joined():
    ok, reasons = load_i.verdict_of(_run())
    assert ok, reasons

    report = load_i.render(_run())
    assert "SEGMENTS JOINED" in report
    assert "PASS" in report


def test_a_table_that_never_reached_audio_ready_fails():
    run = _run()
    run["per_table"][0]["state"] = "WAITING_FOR_CHUNKS"

    ok, reasons = load_i.verdict_of(run)

    assert not ok
    assert any("WAITING_FOR_CHUNKS" in reason for reason in reasons)


def test_bytes_the_server_does_not_have_fail():
    run = _run()
    run["per_table"][1]["manifest"] = "MISMATCH"

    ok, reasons = load_i.verdict_of(run)

    assert not ok
    assert any("different bytes" in reason for reason in reasons)


def test_an_interrupted_table_whose_segments_were_not_joined_fails():
    """The failure 0.6.1 produces: the second segment is spliced in mid-stream,
    so the assembled file stops at the interruption and the duration says so."""
    run = _run()
    run["per_table"][0]["server_seconds"] = 195.0  # only segment 0 survived

    ok, reasons = load_i.verdict_of(run)
    report = load_i.render(run)

    assert not ok
    assert any("195.0s of audio against 435.0s" in reason for reason in reasons)
    assert "NOT JOINED CORRECTLY" in report


def test_server_errors_fail_the_run_and_are_listed():
    run = _run(outcomes={"chunk": {"ok": 90, "5xx": 2}},
               faults=[("10:03:11", "chunk", "5xx", "Internal Server Error")])

    ok, reasons = load_i.verdict_of(run)

    assert not ok
    assert any("failed on the server" in reason for reason in reasons)
    assert "Internal Server Error" in load_i.render(run)


def test_a_run_stopped_by_the_breaker_fails_and_says_why():
    run = _run(aborted="12 server errors or dropped connections (limit 8)")

    ok, reasons = load_i.verdict_of(run)

    assert not ok
    assert any("stopped early" in reason for reason in reasons)
    assert "ABORTED" in load_i.render(run)


def test_the_report_never_leaks_a_token():
    run = _run()
    run["per_table"][0]["notes"] = [f"chunk 3 refused: 401 token {TOKEN}"]

    # only what we put there ourselves: the renderer must not add tokens, and
    # the run dict it renders holds none
    assert TOKEN not in load_i.render(_run())
    assert "token" not in load_i.render(_run()).lower().replace("tokens", "")
