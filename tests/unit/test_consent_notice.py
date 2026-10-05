# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The consent notice is a pure function of the organization data and the
data-handling facts, in the assembly's language, hashed exactly as shown —
so a stored hash proves what a person read. Blank fields are omitted, never
printed as placeholders; the selected providers are named."""

from citizens.services.consent_notice import NOTICE_VERSION, notice_hash, render_notice

HANDLING = {
    "stt_provider": "vosk", "stt_provider_label": "Vosk", "stt_configured": True, "stt_hosted": False,
    "analysis_enabled": True, "analysis_hosted": True, "analysis_provider_label": "Mistral AI",
    "audio_retention_days": 30,
}
ORG = {
    "organization_name": "Comune di Bologna",
    "consent_controller": "",
    "consent_contact": "privacy@example.org",
    "org_address": "Piazza Maggiore 6, Bologna",
    "org_dpo": "dpo@example.org",
    "org_hosting": "Hetzner, Germany",
    "org_authority": "",
}


def test_the_same_inputs_give_the_same_hash_and_a_changed_fact_changes_it():
    one = render_notice("en", HANDLING, organization=ORG)
    two = render_notice("en", dict(HANDLING), organization=dict(ORG))
    assert one.hash == two.hash == notice_hash(NOTICE_VERSION, "en", one.paragraphs)
    assert len(one.hash) == 64
    assert render_notice("en", {**HANDLING, "audio_retention_days": 7}, organization=ORG).hash != one.hash
    assert render_notice("en", HANDLING, organization=ORG, auto_purge=False).hash != one.hash
    assert render_notice("it", HANDLING, organization=ORG).hash != one.hash


def test_the_notice_has_every_section_and_names_the_providers():
    notice = render_notice("en", HANDLING, organization=ORG)
    text = notice.text
    assert text.startswith("Comune di Bologna is recording this discussion and is responsible for your data, "
                           "Piazza Maggiore 6, Bologna. Contact: privacy@example.org. "
                           "Data protection contact: dpo@example.org.")
    assert "the phone on the table records the audio" in text
    assert "Art. 6(1)(a) GDPR" in text and "Art. 9(2)(a) GDPR" in text
    assert "deleted from the phone when the assembly is closed" in text
    assert "transcribed by Vosk on the organisation's own server" in text
    assert "sent to Mistral AI, an outside AI service" in text
    assert "there is no voice recognition" in text
    assert "reviewed by a person before anything is published" in text
    assert "on the organiser's server at Hetzner, Germany. Recipients: Mistral AI." in text
    assert "deleted 30 days after the assembly is closed" in text
    assert "withdrawal of consent at any time" in text and "write to privacy@example.org" in text
    assert "lodge a complaint with the data protection authority of your country" in text
    assert notice.acceptance.startswith("By registering you declare that you have read this notice")
    assert "short anonymous quotations" in notice.acceptance
    assert notice.as_dict()["acceptance"] == notice.paragraphs[-1]
    assert notice.version == NOTICE_VERSION and notice.language == "en"


def test_blank_organization_fields_are_omitted_and_italian_has_the_garante():
    handling = {
        **HANDLING, "stt_provider": "deepgram", "stt_provider_label": "Deepgram", "stt_hosted": True,
        "analysis_enabled": False, "audio_retention_days": 0,
    }
    notice = render_notice("it-IT", handling, organization={})
    text = notice.text
    assert text.startswith("L'organizzazione registra questa discussione ed è responsabile dei tuoi dati.")
    assert "Contatto:" not in text and "presso" not in text
    assert "inviata a Deepgram, un servizio esterno" in text
    assert "Destinatari: Deepgram." in text
    assert "Non viene eseguita alcuna analisi" in text
    assert "finché chi organizza non la cancella" in text
    assert "Garante per la protezione dei dati personali (www.garanteprivacy.it)" in text
    assert notice.language == "it"
    # a language without a notice reads English
    english = render_notice("de", {})
    assert english.text.startswith("The organiser is recording this discussion")
    assert "No transcription engine is configured" in english.text
    assert "the data protection authority of your country" in english.text


def test_a_local_analysis_endpoint_and_a_custom_authority():
    notice = render_notice(
        "en", {**HANDLING, "analysis_hosted": False, "analysis_provider_label": "local"},
        organization={**ORG, "org_authority": "the Garante per la protezione dei dati personali"},
    )
    assert "summarised by an AI model running on the organisation's own server" in notice.text
    assert "Recipients:" not in notice.text  # Vosk local, analysis local: nobody outside
    assert "lodge a complaint with the Garante per la protezione dei dati personali" in notice.text
