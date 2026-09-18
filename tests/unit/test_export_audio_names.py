# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every exported recording must retain its own bytes after extraction."""

import json
import zipfile

import pytest

from citizens.db.models import Assembly, Recording, Round, Table
from citizens.db.models.base import utcnow
from citizens.db.session import session_scope
from citizens.services import files, provider_config


@pytest.mark.parametrize("mode", ["plenary", "orchestrated"])
def test_archive_names_and_manifest_preserve_each_recording(database, monkeypatch, tmp_path, mode):
    monkeypatch.setattr(provider_config, "analysis_enabled_cached", lambda: False)
    monkeypatch.setattr("citizens.services.branding.logo_path", lambda: None)
    monkeypatch.setattr("citizens.services.branding.organization_name", lambda: "")
    monkeypatch.setattr("citizens.services.report_pdf.render_pdf", lambda *_: b"pdf")
    with session_scope() as session:
        assembly = Assembly(name="Same table", created_by="tester", recording_mode=mode)
        session.add(assembly)
        session.flush()
        round_ = Round(assembly_id=assembly.id, position=1, title="Round", question="Question")
        session.add(round_)
        session.flush()
        table = Table(round_id=round_.id, number=1)
        session.add(table)
        session.flush()
        expected = {}
        for index in range(3):
            path = database.app_persistent_storage / f"recording-{index}.webm"
            path.write_bytes(f"audio from phone {index}".encode())
            recording = Recording(
                assembly_id=assembly.id, round_id=round_.id, table_id=table.id,
                table_number=1, state="AUDIO_READY", canonical_audio_path=path.name,
                superseded_at=utcnow() if mode == "orchestrated" and index < 2 else None,
            )
            session.add(recording)
            session.flush()
            expected[recording.id] = path.read_bytes()
        archive_path = files.build_audio_zip(session, assembly)
        with zipfile.ZipFile(archive_path) as archive:
            assert len(archive.namelist()) == len(set(archive.namelist())) == 3
            archive.extractall(tmp_path / "audio")
            assert {p.read_bytes() for p in (tmp_path / "audio").iterdir()} == set(expected.values())
        archive_path = files.build_session_export(session, assembly)
        with zipfile.ZipFile(archive_path) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            names = [row["audio_file"] for row in manifest["recordings"]]
            assert len(set(names)) == 3
            assert len(archive.namelist()) == len(set(archive.namelist()))
            for row in manifest["recordings"]:
                assert archive.read(row["audio_file"]) == expected[row["id"]]
