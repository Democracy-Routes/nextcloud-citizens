# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The consent notice, rendered by the server and hashed exactly as shown.

The paper form (docs/consent-form.md) says who records, what, with which
engine, how long audio is kept, that names are pseudonymised, what rights a
person has and on which legal basis. The phone, the participant's own page,
the event kit and the paper now say the same thing: this module builds the
notice from the organization data in Settings and the live data-handling
facts, so it cannot drift from what the app does — and the hash of the
rendered text is stored with every consent, so the record proves what was
read.

A pure function of its inputs: callers read `data_handling_summary()` and
`organization_data()` from the config snapshot (never inside a database
transaction) and hand them in. Blank organization fields are omitted, never
printed as placeholders.
"""

import hashlib
from dataclasses import dataclass

from citizens.services.report_text import normalize_language

#: bumped whenever the wording changes; old consents keep their old hash
NOTICE_VERSION = "2026-10.2"

_TEXT = {
    "en": {
        "who": "{controller} is recording this discussion and is responsible for your data{address}.",
        "who_contact": " Contact: {contact}.",
        "who_dpo": " Data protection contact: {dpo}.",
        "what": (
            "During the discussion at your table, the phone on the table records the audio. "
            "From that recording we produce a written transcript and, with the help of "
            "artificial intelligence, a summary of the points raised (proposals, agreements, "
            "concerns, questions, minority views). The name you give when registering, and "
            "the email if you choose to give one, are kept in the participant list."
        ),
        "why": (
            "Why, and on what legal basis: to document the discussion faithfully and to "
            "produce the assembly's report. The legal basis is your explicit consent "
            "(Art. 6(1)(a) GDPR and, because what is said in a debate may reveal political "
            "opinions, Art. 9(2)(a) GDPR). You are free not to consent: the discussion at "
            "your table can go on without the phone recording you."
        ),
        "how_phone_purge": (
            "The phone at your table keeps a copy of the recording until the server has "
            "received it; the copy is deleted from the phone when the assembly is closed."
        ),
        "how_phone_keep": (
            "The phone at your table keeps a copy of the recording until the server has "
            "received it and the organiser clears the phones."
        ),
        "engine_hosted": (
            "The recording is sent to {engine}, a service outside the organisation's own "
            "server, to be turned into text."
        ),
        "engine_local": (
            "The recording is transcribed by {engine} on the organisation's own server; the "
            "audio is not sent to any outside company."
        ),
        "engine_none": "No transcription engine is configured, so the audio stays on this server.",
        "analysis_hosted": (
            "The written transcript — never the audio — is sent to {provider}, an outside AI "
            "service, to draft the summary and the findings."
        ),
        "analysis_hosted_unnamed": (
            "The written transcript — never the audio — is sent to an outside AI service to "
            "draft the summary and the findings."
        ),
        "analysis_local": (
            "The written transcript is summarised by an AI model running on the organisation's "
            "own server."
        ),
        "analysis_none": "No AI analysis is run; only the transcript is produced.",
        "speakers": (
            "Speakers are labelled only as \"Speaker 1\", \"Speaker 2\": there is no voice "
            "recognition, and the recording is not linked to your identity. Names spoken "
            "aloud do appear in the transcript as they were said; listed participants' names "
            "are replaced by pseudonyms before any text leaves the server."
        ),
        "review": (
            "Every AI-produced result is reviewed by a person before anything is published, and "
            "the report states that AI was used. The report may contain short anonymous "
            "quotations from your table; it is shared with participants and may be published "
            "by the organiser."
        ),
        "where": "Where your data is kept: on the organiser's server{hosting}.{recipients}",
        "where_hosting": " at {hosting}",
        "where_recipients": " Recipients: {recipients}.",
        "retention_days": (
            "How long: the audio recording is deleted {days} days after the assembly is closed. "
            "The transcript, the summaries and the report are kept as the record of the "
            "assembly, together with the participant list."
        ),
        "retention_none": (
            "How long: the audio recording is kept until an organiser deletes it. The "
            "transcript, the summaries and the report are kept as the record of the assembly, "
            "together with the participant list."
        ),
        "rights": (
            "Your rights: access, rectification, erasure, restriction, portability, objection, "
            "and withdrawal of consent at any time (it does not affect processing already "
            "done){contact}. Because voices are not separated in the recording, erasure after "
            "the session means deleting your table's recording and transcript on request. You "
            "may lodge a complaint with {authority}."
        ),
        "rights_contact": " — write to {contact}",
        "authority_default": "the data protection authority of your country",
        "accept": (
            "By registering you declare that you have read this notice and you consent to the "
            "audio recording of the discussion at your table, to its transcription and "
            "AI-assisted analysis, and to short anonymous quotations from your table in the "
            "assembly's report, which may be published."
        ),
        "fallback_controller": "The organiser",
    },
    "it": {
        "who": "{controller} registra questa discussione ed è responsabile dei tuoi dati{address}.",
        "who_contact": " Contatto: {contact}.",
        "who_dpo": " Contatto per la protezione dei dati: {dpo}.",
        "what": (
            "Durante la discussione al tuo tavolo, il telefono sul tavolo registra l'audio. "
            "Dalla registrazione produciamo una trascrizione scritta e, con l'aiuto "
            "dell'intelligenza artificiale, una sintesi dei punti emersi (proposte, accordi, "
            "preoccupazioni, domande, posizioni di minoranza). Il nome che indichi al momento "
            "della registrazione, e l'email se scegli di fornirla, sono conservati nell'elenco "
            "dei partecipanti."
        ),
        "why": (
            "Perché, e su quale base giuridica: per documentare fedelmente la discussione e "
            "produrre il rapporto dell'assemblea. La base giuridica è il tuo consenso esplicito "
            "(art. 6, par. 1, lett. a) del GDPR e, poiché ciò che si dice in un dibattito può "
            "rivelare opinioni politiche, art. 9, par. 2, lett. a) del GDPR). Sei libero di non "
            "acconsentire: la discussione al tuo tavolo può proseguire senza che il telefono ti "
            "registri."
        ),
        "how_phone_purge": (
            "Il telefono al tuo tavolo conserva una copia della registrazione finché il server "
            "non l'ha ricevuta; la copia viene cancellata dal telefono alla chiusura "
            "dell'assemblea."
        ),
        "how_phone_keep": (
            "Il telefono al tuo tavolo conserva una copia della registrazione finché il server "
            "non l'ha ricevuta e chi organizza non svuota i telefoni."
        ),
        "engine_hosted": (
            "La registrazione viene inviata a {engine}, un servizio esterno al server "
            "dell'organizzazione, per essere trasformata in testo."
        ),
        "engine_local": (
            "La registrazione viene trascritta da {engine} sul server dell'organizzazione; "
            "l'audio non viene inviato ad alcuna società esterna."
        ),
        "engine_none": (
            "Nessun motore di trascrizione è configurato, quindi l'audio resta su questo server."
        ),
        "analysis_hosted": (
            "La trascrizione scritta — mai l'audio — viene inviata a {provider}, un servizio di "
            "IA esterno, per redigere la sintesi e i risultati."
        ),
        "analysis_hosted_unnamed": (
            "La trascrizione scritta — mai l'audio — viene inviata a un servizio di IA esterno "
            "per redigere la sintesi e i risultati."
        ),
        "analysis_local": (
            "La trascrizione scritta viene sintetizzata da un modello di IA in esecuzione sul "
            "server dell'organizzazione."
        ),
        "analysis_none": (
            "Non viene eseguita alcuna analisi con IA; viene prodotta solo la trascrizione."
        ),
        "speakers": (
            "Chi parla è indicato solo come \"Speaker 1\", \"Speaker 2\": non c'è riconoscimento "
            "vocale e la registrazione non è collegata alla tua identità. I nomi pronunciati ad "
            "alta voce compaiono nella trascrizione così come sono stati detti; i nomi dei "
            "partecipanti registrati vengono sostituiti da pseudonimi prima che qualsiasi testo "
            "lasci il server."
        ),
        "review": (
            "Ogni risultato prodotto dall'IA viene rivisto da una persona prima di qualsiasi "
            "pubblicazione, e il rapporto dichiara l'uso dell'IA. Il rapporto può contenere "
            "brevi citazioni anonime dal tuo tavolo; viene condiviso con i partecipanti e può "
            "essere pubblicato da chi organizza."
        ),
        "where": "Dove sono conservati i tuoi dati: sul server di chi organizza{hosting}.{recipients}",
        "where_hosting": " presso {hosting}",
        "where_recipients": " Destinatari: {recipients}.",
        "retention_days": (
            "Per quanto tempo: la registrazione audio viene cancellata {days} giorni dopo la "
            "chiusura dell'assemblea. Trascrizione, sintesi e rapporto sono conservati come "
            "documentazione dell'assemblea, insieme all'elenco dei partecipanti."
        ),
        "retention_none": (
            "Per quanto tempo: la registrazione audio viene conservata finché chi organizza non "
            "la cancella. Trascrizione, sintesi e rapporto sono conservati come documentazione "
            "dell'assemblea, insieme all'elenco dei partecipanti."
        ),
        "rights": (
            "I tuoi diritti: accesso, rettifica, cancellazione, limitazione, portabilità, "
            "opposizione e revoca del consenso in qualsiasi momento (senza pregiudicare i "
            "trattamenti già effettuati){contact}. Poiché le voci non sono separate nella "
            "registrazione, la cancellazione dopo la sessione comporta, su richiesta, "
            "l'eliminazione della registrazione e della trascrizione del tuo tavolo. Puoi "
            "proporre reclamo a {authority}."
        ),
        "rights_contact": " — scrivi a {contact}",
        "authority_default": (
            "Garante per la protezione dei dati personali (www.garanteprivacy.it)"
        ),
        "accept": (
            "Registrandoti dichiari di aver letto questa informativa e acconsenti alla "
            "registrazione audio della discussione al tuo tavolo, alla sua trascrizione e "
            "analisi assistita dall'IA, e all'inserimento di brevi citazioni anonime dal tuo "
            "tavolo nel rapporto dell'assemblea, che potrà essere pubblicato."
        ),
        "fallback_controller": "L'organizzazione",
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

    @property
    def acceptance(self) -> str:
        """The sentence the one acceptance box carries — the last paragraph."""
        return self.paragraphs[-1]

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "language": self.language,
            "hash": self.hash,
            "paragraphs": list(self.paragraphs),
            "acceptance": self.acceptance,
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
    organization: dict | None = None,
    auto_purge: bool = True,
) -> Notice:
    """The notice for an assembly.

    `handling` is data_handling_summary() with the assembly's own retention
    merged in; `organization` is organization_data() (address, DPO, hosting,
    authority — any may be blank); `controller`/`contact`/`organization_name`
    are accepted for callers that pass them separately. `auto_purge` is the
    assembly's "clear the phones at closing" switch.
    """
    org = dict(organization or {})
    lang = normalize_language(language)
    strings = _TEXT.get(lang, _TEXT["en"])

    def t(key: str, **fmt) -> str:
        template = strings.get(key) or _TEXT["en"][key]
        return template.format(**fmt) if fmt else template

    controller = (controller or org.get("consent_controller") or organization_name
                  or org.get("organization_name") or "").strip() or t("fallback_controller")
    contact = (contact or org.get("consent_contact") or "").strip()
    address = (org.get("org_address") or "").strip()
    dpo = (org.get("org_dpo") or "").strip()
    hosting = (org.get("org_hosting") or "").strip()
    authority = (org.get("org_authority") or "").strip() or t("authority_default")

    who = t("who", controller=controller, address=f", {address}" if address else "")
    if contact:
        who += t("who_contact", contact=contact)
    if dpo:
        who += t("who_dpo", dpo=dpo)

    paragraphs = [who, t("what"), t("why")]

    # how it works: the phone's copy, the engine, the analysis, the speakers
    how = [t("how_phone_purge") if auto_purge else t("how_phone_keep")]
    provider = handling.get("stt_provider") or ""
    engine = handling.get("stt_provider_label") or provider
    recipients: list[str] = []
    if not handling.get("stt_configured", bool(provider)):
        how.append(t("engine_none"))
    elif handling.get("stt_hosted"):
        how.append(t("engine_hosted", engine=engine))
        recipients.append(engine)
    else:
        how.append(t("engine_local", engine=engine))
    analysis_label = handling.get("analysis_provider_label") or ""
    if not handling.get("analysis_enabled"):
        how.append(t("analysis_none"))
    elif handling.get("analysis_hosted"):
        if analysis_label and analysis_label != "local":
            how.append(t("analysis_hosted", provider=analysis_label))
            if analysis_label not in recipients:
                recipients.append(analysis_label)
        else:
            how.append(t("analysis_hosted_unnamed"))
    else:
        how.append(t("analysis_local"))
    paragraphs.append(" ".join(how))
    paragraphs.append(t("speakers"))
    paragraphs.append(t("review"))

    paragraphs.append(
        t(
            "where",
            hosting=t("where_hosting", hosting=hosting) if hosting else "",
            recipients=t("where_recipients", recipients=", ".join(recipients)) if recipients else "",
        )
    )
    days = int(handling.get("audio_retention_days") or 0)
    paragraphs.append(t("retention_days", days=days) if days > 0 else t("retention_none"))
    paragraphs.append(
        t(
            "rights",
            contact=t("rights_contact", contact=contact) if contact else "",
            authority=authority,
        )
    )
    paragraphs.append(t("accept"))
    return Notice(NOTICE_VERSION, lang, notice_hash(NOTICE_VERSION, lang, paragraphs), paragraphs)
