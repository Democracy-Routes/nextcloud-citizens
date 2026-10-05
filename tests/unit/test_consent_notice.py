# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The consent notice is a pure function of settings and the data-handling
facts, in the assembly's language, hashed exactly as shown — so a stored hash
proves what a person read."""

from citizens.services.consent_notice import NOTICE_VERSION, notice_hash, render_notice

HANDLING = {
    "stt_provider": "vosk", "stt_configured": True, "stt_hosted": False,
    "analysis_enabled": True, "analysis_hosted": True, "audio_retention_days": 30,
}


def test_the_same_inputs_give_the_same_hash_and_a_changed_fact_changes_it():
    one = render_notice("en", HANDLING, controller="Comune", contact="privacy@example.org")
    two = render_notice("en", dict(HANDLING), controller="Comune", contact="privacy@example.org")
    assert one.hash == two.hash == notice_hash(NOTICE_VERSION, "en", one.paragraphs)
    assert len(one.hash) == 64
    other = render_notice("en", {**HANDLING, "audio_retention_days": 7}, controller="Comune")
    assert other.hash != one.hash
    assert render_notice("it", HANDLING, controller="Comune").hash != one.hash


def test_the_notice_says_who_what_engine_analysis_retention_names_rights_basis():
    notice = render_notice("en", HANDLING, controller="", contact="privacy@example.org",
                           organization_name="Comune di Bologna")
    text = notice.text
    assert text.startswith("Comune di Bologna is recording this discussion")
    assert "Contact: privacy@example.org." in text
    assert "transcribed by Vosk on the organisation's own server" in text
    assert "outside AI service" in text
    assert "deleted 30 days after the assembly ends" in text
    assert "replaced by pseudonyms" in text
    assert "withdraw your consent at any time by contacting privacy@example.org" in text
    assert "Art. 6(1)(a) and Art. 9(2)(a)" in text
    assert notice.version == NOTICE_VERSION and notice.language == "en"


def test_italian_and_the_fallbacks():
    notice = render_notice("it-IT", {**HANDLING, "stt_provider": "deepgram", "stt_hosted": True,
                                     "analysis_enabled": False, "audio_retention_days": 0})
    text = notice.text
    assert text.startswith("L'organizzazione registra questa discussione")
    assert "trascritto da Deepgram, un servizio esterno" in text
    assert "Non viene eseguita alcuna analisi" in text
    assert "finché un organizzatore non la cancella" in text
    assert notice.language == "it"
    # a language without a notice reads English, with the organiser unnamed
    english = render_notice("de", {})
    assert english.language == "de"
    assert english.text.startswith("The organiser is recording this discussion")
    assert "No transcription engine is configured" in english.text
