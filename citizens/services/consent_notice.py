# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The consent notice, rendered by the server and hashed exactly as shown.

The paper form (docs/consent-form.md) said who records, what, with which
engine, how long audio is kept, that names are pseudonymised, what rights a
person has and on which legal basis. The phone now shows the same, built
from settings and the live data-handling facts, so it cannot drift from what
the app does — and the hash of the rendered text is stored with every
consent, so the record proves what was read.

A pure function of its inputs: callers read `data_handling_summary()` and
the two consent settings from the config snapshot (never inside a database
transaction) and hand them in.
"""

import hashlib
from dataclasses import dataclass

from citizens.services.report_text import normalize_language

NOTICE_VERSION = "2026-10"

_PROVIDER_NAMES = {
    "vosk": "Vosk",
    "whisper": "Whisper",
    "mistral": "Mistral",
    "deepgram": "Deepgram",
}

_TEXT = {
    "en": {
        "who": "{controller} is recording this discussion and is responsible for the data.",
        "who_contact": (
            "{controller} is recording this discussion and is responsible for the data. "
            "Contact: {contact}."
        ),
        "what": (
            "The phone on the table records the conversation. The recording is turned into a "
            "written transcript and analysed to produce the report of this assembly."
        ),
        "engine_hosted": (
            "The audio is transcribed by {engine}, a service outside the organisation's own server."
        ),
        "engine_local": (
            "The audio is transcribed by {engine} on the organisation's own server; it is not sent "
            "to any outside company."
        ),
        "engine_none": "No transcription engine is configured, so the audio stays on this server.",
        "analysis_hosted": (
            "The written transcript — never the audio — is also sent to an outside AI service to "
            "draft summaries and findings."
        ),
        "analysis_local": (
            "The written transcript is summarised by an AI model on the organisation's own server."
        ),
        "analysis_none": "No AI analysis is run; only the transcript is produced.",
        "retention_days": (
            "The audio recording is deleted {days} days after the assembly ends. The transcript "
            "and the report are kept."
        ),
        "retention_none": (
            "The audio recording is kept until an organiser deletes it. The transcript and the "
            "report are kept."
        ),
        "names": (
            "Speakers appear only as \"Speaker 1\", \"Speaker 2\". Participants' names are "
            "replaced by pseudonyms before any text leaves the server. A name said out loud "
            "is written down as spoken."
        ),
        "review": "Nothing is published until a person has reviewed it.",
        "rights": (
            "Taking part is voluntary. You can refuse, ask what is held about you, have it "
            "erased, or withdraw your consent at any time{contact}; withdrawing does not undo "
            "what was processed before."
        ),
        "rights_contact": " by contacting {contact}",
        "basis": (
            "Legal basis: your explicit consent (GDPR Art. 6(1)(a) and Art. 9(2)(a) — opinions "
            "expressed in a political discussion are special-category data)."
        ),
    },
    "it": {
        "who": "{controller} registra questa discussione ed è responsabile dei dati.",
        "who_contact": (
            "{controller} registra questa discussione ed è responsabile dei dati. "
            "Contatto: {contact}."
        ),
        "what": (
            "Il telefono sul tavolo registra la conversazione. La registrazione viene trasformata "
            "in una trascrizione scritta e analizzata per produrre il rapporto di questa assemblea."
        ),
        "engine_hosted": (
            "L'audio viene trascritto da {engine}, un servizio esterno al server dell'organizzazione."
        ),
        "engine_local": (
            "L'audio viene trascritto da {engine} sul server dell'organizzazione; non viene inviato "
            "ad alcuna società esterna."
        ),
        "engine_none": (
            "Nessun motore di trascrizione è configurato, quindi l'audio resta su questo server."
        ),
        "analysis_hosted": (
            "La trascrizione scritta — mai l'audio — viene inviata anche a un servizio di IA esterno "
            "per redigere sintesi e risultati."
        ),
        "analysis_local": (
            "La trascrizione scritta viene sintetizzata da un modello di IA sul server "
            "dell'organizzazione."
        ),
        "analysis_none": "Non viene eseguita alcuna analisi con IA; viene prodotta solo la trascrizione.",
        "retention_days": (
            "La registrazione audio viene cancellata {days} giorni dopo la fine dell'assemblea. "
            "La trascrizione e il rapporto vengono conservati."
        ),
        "retention_none": (
            "La registrazione audio viene conservata finché un organizzatore non la cancella. "
            "La trascrizione e il rapporto vengono conservati."
        ),
        "names": (
            "Chi parla compare solo come \"Speaker 1\", \"Speaker 2\". I nomi dei partecipanti "
            "vengono sostituiti da pseudonimi prima che qualsiasi testo lasci il server. Un nome "
            "detto ad alta voce viene trascritto così com'è stato detto."
        ),
        "review": "Nulla viene pubblicato prima che una persona lo abbia rivisto.",
        "rights": (
            "La partecipazione è volontaria. Puoi rifiutare, chiedere quali dati ti riguardano, "
            "farli cancellare o revocare il consenso in qualsiasi momento{contact}; la revoca non "
            "annulla ciò che è stato trattato prima."
        ),
        "rights_contact": " contattando {contact}",
        "basis": (
            "Base giuridica: il tuo consenso esplicito (GDPR art. 6(1)(a) e art. 9(2)(a) — le "
            "opinioni espresse in una discussione politica sono dati di categoria particolare)."
        ),
    },
}


@dataclass(frozen=True)
class Notice:
    version: str
    language: str
    hash: str
    paragraphs: list[str]

    @property
    def text(self) -> str:
        return "\n".join(self.paragraphs)

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "language": self.language,
            "hash": self.hash,
            "paragraphs": list(self.paragraphs),
        }


def notice_hash(version: str, language: str, paragraphs: list[str]) -> str:
    payload = f"{version}\n{language}\n" + "\n".join(paragraphs)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def render_notice(
    language: str | None,
    handling: dict,
    *,
    controller: str = "",
    contact: str = "",
    organization_name: str = "",
) -> Notice:
    """The notice for an assembly: `handling` is data_handling_summary() with
    the assembly's own retention already merged in; `controller` falls back
    to the organization name, and to "The organiser" when both are empty."""
    lang = normalize_language(language)
    strings = _TEXT.get(lang, _TEXT["en"])

    def t(key: str, **fmt) -> str:
        template = strings.get(key) or _TEXT["en"][key]
        return template.format(**fmt) if fmt else template

    who = (controller or organization_name or "").strip() or (
        "L'organizzazione" if lang == "it" else "The organiser"
    )
    contact = (contact or "").strip()
    paragraphs = [
        t("who_contact", controller=who, contact=contact) if contact else t("who", controller=who),
        t("what"),
    ]
    provider = handling.get("stt_provider") or ""
    engine = _PROVIDER_NAMES.get(provider, provider)
    if not handling.get("stt_configured", bool(provider)):
        paragraphs.append(t("engine_none"))
    elif handling.get("stt_hosted"):
        paragraphs.append(t("engine_hosted", engine=engine))
    else:
        paragraphs.append(t("engine_local", engine=engine))
    if not handling.get("analysis_enabled"):
        paragraphs.append(t("analysis_none"))
    elif handling.get("analysis_hosted"):
        paragraphs.append(t("analysis_hosted"))
    else:
        paragraphs.append(t("analysis_local"))
    days = int(handling.get("audio_retention_days") or 0)
    paragraphs.append(t("retention_days", days=days) if days > 0 else t("retention_none"))
    paragraphs.append(t("names"))
    paragraphs.append(t("review"))
    paragraphs.append(
        t("rights", contact=t("rights_contact", contact=contact) if contact else "")
    )
    paragraphs.append(t("basis"))
    return Notice(NOTICE_VERSION, lang, notice_hash(NOTICE_VERSION, lang, paragraphs), paragraphs)
