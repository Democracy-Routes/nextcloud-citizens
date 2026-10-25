# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The built-in Vosk engine's model catalogue and directory scan (0.8)."""

from citizens.services import vosk_builtin, vosk_models


def _fake_model(root, name, usable=True):
    directory = root / "models" / name
    (directory / "am").mkdir(parents=True)
    (directory / "am" / "final.mdl").write_bytes(b"x" * 1000)
    if usable:
        (directory / "conf").mkdir()
        (directory / "conf" / "model.conf").write_text("--sample-frequency=16000\n")
    return directory


def test_the_catalogue_covers_the_five_languages_small_and_large():
    languages = {entry["language"] for entry in vosk_models.CATALOGUE}
    assert languages == {"it", "en", "de", "fr", "es"}
    for language in languages:
        kinds = {e["kind"] for e in vosk_models.CATALOGUE if e["language"] == language}
        assert kinds == {"small", "large"}
    assert all(vosk_models.NAME_RE.match(e["name"]) for e in vosk_models.CATALOGUE)


def test_installed_models_are_read_from_the_directory(tmp_path):
    _fake_model(tmp_path, "vosk-model-small-it-0.22")
    _fake_model(tmp_path, "vosk-model-mine-xx-1.0", usable=False)
    (tmp_path / "models" / "notes.txt").write_text("not a model")
    found = vosk_models.installed(tmp_path)
    assert [m["name"] for m in found] == ["vosk-model-mine-xx-1.0", "vosk-model-small-it-0.22"]
    small = next(m for m in found if m["name"] == "vosk-model-small-it-0.22")
    assert small["language"] == "it" and small["kind"] == "small" and small["usable"] is True
    assert small["size_bytes"] > 1000
    custom = next(m for m in found if m["kind"] == "custom")
    assert custom["usable"] is False and custom["language"] == "mi"


def test_the_overview_lists_what_is_left_to_install(tmp_path, monkeypatch):
    _fake_model(tmp_path, "vosk-model-small-it-0.22")
    monkeypatch.setattr(vosk_models, "_root", lambda: tmp_path)
    vosk_models._set_progress("vosk-model-it-0.22", phase="downloading", received=10, total=100)
    overview = vosk_models.overview(tmp_path)
    names = [e["name"] for e in overview["available"]]
    assert "vosk-model-small-it-0.22" not in names and "vosk-model-it-0.22" in names
    large = next(e for e in overview["available"] if e["name"] == "vosk-model-it-0.22")
    assert large["progress"]["phase"] == "downloading" and large["progress"]["received"] == 10
    assert overview["engine"]["running"] is False
    vosk_models.PROGRESS.clear()


def test_directory_bytes_and_memory_reading(tmp_path):
    _fake_model(tmp_path, "m")
    assert vosk_builtin.directory_bytes(tmp_path / "models" / "m") > 1000
    available = vosk_builtin.memory_available()
    assert available is None or available >= 0
