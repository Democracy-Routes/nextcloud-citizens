# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The fixed wording of an assembly report, per language.

The model writes findings and summaries in the assembly's language; every
heading, label and note printed around them comes from here, keyed on that
same language. `en` is the reference catalogue and the automatic fallback:
a language that lacks a key prints the English wording for it, so a partial
translation degrades to a readable report rather than a KeyError.

Markdown and PDF syntax stays in the renderers — the catalogue holds text
only, so one entry serves both exports and a translator never sees `##`.

Placeholders use str.format names; the parity test checks that a translation
uses exactly the placeholders its English original does.
"""

from datetime import date

#: Finding types in the order a deliberation report groups them
#: (institutional reading order, divergence highlighted).
TYPE_ORDER = (
    "proposal", "agreement", "disagreement", "concern",
    "question", "minority_position", "new_idea",
)

_MONTHS_EN = (
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
)
_MONTHS_IT = (
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
    "agosto", "settembre", "ottobre", "novembre", "dicembre",
)
_MONTHS_DE = (
    "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
    "August", "September", "Oktober", "November", "Dezember",
)
_MONTHS_FR = (
    "janvier", "février", "mars", "avril", "mai", "juin", "juillet",
    "août", "septembre", "octobre", "novembre", "décembre",
)
_MONTHS_ES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
    "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)


def _months(names: tuple[str, ...]) -> dict[str, str]:
    return {f"month.{number}": name for number, name in enumerate(names, start=1)}


CATALOGUE: dict[str, dict[str, str]] = {
    "en": {
        # cover
        "assembly_report": "Assembly Report",
        "final_report": "FINAL REPORT",
        "closed_on": "closed {date}",
        "interim_report": "INTERIM REPORT",
        "tables_completed_all_rounds": (
            "{complete} of {expected} tables have completed all rounds"
        ),
        "tables_contributing": "Tables contributing: {contributed} of {expected}",
        "participants": "Participants: {count} (expected {expected})",
        "tables": "Tables: {count}",
        "language": "Language: {code}",
        "participants_expected": "{count} participants (expected {expected})",
        "tables_count": "{count} tables",
        "tables_contributed_to_report": (
            "{contributed} of {expected} tables contributed to this report"
        ),
        # method
        "method_heading": "Method",
        "method": (
            "In-person citizens' assembly: participants discussed in small tables; "
            "a phone at each table recorded the conversation, which was transcribed "
            "and analyzed per table, then aggregated across tables."
        ),
        "method_diarized": (
            "In-person citizens' assembly: participants discussed in small tables; "
            "a phone at each table recorded the conversation, which was transcribed "
            "with speaker diarization and analyzed per table, then aggregated across tables."
        ),
        "methodology_note": (
            "AI was used to assist transcription and analysis. "
            "Findings were reviewed by a human organizer; discussion summaries are "
            "AI-generated neutral descriptions. "
            "“Mentioned at N tables” describes how many discussion tables raised a topic; "
            "it is not a measure of participant support."
        ),
        "live_transcript_note": (
            "This assembly's transcripts come from the live captions produced while "
            "the tables were speaking, not from a separate transcription of the "
            "complete recordings. Captions are made under time pressure and can miss "
            "speech the engine could not keep up with, so passages may be absent or "
            "less accurate than the audio itself."
        ),
        "device_replaced_note": (
            "At least one table's phone stopped working during a round and the "
            "discussion continued on another device. Both parts were transcribed and "
            "analysed together as one conversation; a short stretch between them was "
            "not recorded."
        ),
        # executive summary (PDF)
        "executive_summary": "Executive summary",
        "executive_summary_note": (
            "AI-generated overview of each round across all tables; details and "
            "human-reviewed findings follow."
        ),
        # rounds
        "round": "Round {position}",
        "round_titled": "Round {position} — {title}",
        "ai_summary": "AI summary",
        "speaking_balance": "Speaking balance",
        "voice": "Voice {label}",
        "others": "Others",
        "voices_caveat": (
            "Detected voices, not identified by name — from the clearest single "
            "recording. Talk-time, not influence."
        ),
        "across_all_tables": "Across all tables",
        "table_detail": "Table detail",
        "table": "Table {number}",
        "no_findings_yet": "No findings for this round yet.",
        # findings
        "draft_not_reviewed": "DRAFT — not yet reviewed",
        "draft_badge": "draft — not reviewed",
        "mentioned_at_tables": "Mentioned at {count} table(s)",
        "mentioned_at_one_table": "Mentioned at {count} table(s)",
        "speaker": "Speaker",
        "evidence_removed": "Evidence removed with the transcript.",
        "type_plural.proposal": "Proposals",
        "type_plural.agreement": "Points of consensus",
        "type_plural.disagreement": "Points of divergence",
        "type_plural.concern": "Concerns raised",
        "type_plural.question": "Open questions",
        "type_plural.minority_position": "Minority positions",
        "type_plural.new_idea": "Emerging ideas",
        "type_plural.other": "Other findings",
        "type_singular.proposal": "Proposal",
        "type_singular.agreement": "Point of consensus",
        "type_singular.disagreement": "Point of divergence",
        "type_singular.concern": "Concern",
        "type_singular.question": "Open question",
        "type_singular.minority_position": "Minority position",
        "type_singular.new_idea": "Emerging idea",
        # dates
        "date_format": "{day} {month} {year}",
        **_months(_MONTHS_EN),
    },
    "it": {
        "assembly_report": "Rapporto dell'assemblea",
        "final_report": "RAPPORTO FINALE",
        "closed_on": "chiuso il {date}",
        "interim_report": "RAPPORTO PROVVISORIO",
        "tables_completed_all_rounds": (
            "{complete} tavoli su {expected} hanno completato tutti i turni"
        ),
        "tables_contributing": "Tavoli che hanno contribuito: {contributed} su {expected}",
        "participants": "Partecipanti: {count} (previsti {expected})",
        "tables": "Tavoli: {count}",
        "language": "Lingua: {code}",
        "participants_expected": "{count} partecipanti (previsti {expected})",
        "tables_count": "{count} tavoli",
        "tables_contributed_to_report": (
            "{contributed} tavoli su {expected} hanno contribuito a questo rapporto"
        ),
        "method_heading": "Metodo",
        "method": (
            "Assemblea dei cittadini in presenza: i partecipanti hanno discusso in "
            "piccoli tavoli; un telefono a ogni tavolo ha registrato la conversazione, "
            "che è stata trascritta e analizzata tavolo per tavolo, poi aggregata "
            "tra tutti i tavoli."
        ),
        "method_diarized": (
            "Assemblea dei cittadini in presenza: i partecipanti hanno discusso in "
            "piccoli tavoli; un telefono a ogni tavolo ha registrato la conversazione, "
            "che è stata trascritta con la distinzione delle voci e analizzata tavolo "
            "per tavolo, poi aggregata tra tutti i tavoli."
        ),
        "methodology_note": (
            "L'IA è stata utilizzata a supporto della trascrizione e dell'analisi. "
            "I risultati sono stati revisionati da un organizzatore; le sintesi delle "
            "discussioni sono descrizioni neutrali generate dall'IA. "
            "«Menzionato in N tavoli» indica in quanti tavoli di discussione è emerso "
            "un tema; non è una misura del sostegno dei partecipanti."
        ),
        "live_transcript_note": (
            "Le trascrizioni di questa assemblea provengono dai sottotitoli in tempo "
            "reale prodotti mentre i tavoli parlavano, non da una trascrizione separata "
            "delle registrazioni complete. I sottotitoli sono generati sotto pressione "
            "di tempo e possono perdere parti di parlato che il motore non è riuscito a "
            "seguire, quindi alcuni passaggi potrebbero mancare o essere meno accurati "
            "dell'audio stesso."
        ),
        "device_replaced_note": (
            "Il telefono di almeno un tavolo ha smesso di funzionare durante un turno e "
            "la discussione è proseguita su un altro dispositivo. Entrambe le parti sono "
            "state trascritte e analizzate insieme come un'unica conversazione; un breve "
            "tratto tra le due non è stato registrato."
        ),
        "executive_summary": "Sintesi esecutiva",
        "executive_summary_note": (
            "Panoramica generata dall'IA di ciascun turno in tutti i tavoli; seguono i "
            "dettagli e i risultati revisionati da una persona."
        ),
        "round": "Turno {position}",
        "round_titled": "Turno {position} — {title}",
        "ai_summary": "Sintesi IA",
        "speaking_balance": "Equilibrio degli interventi",
        "voice": "Voce {label}",
        "others": "Altri",
        "voices_caveat": (
            "Voci rilevate, non identificate per nome — dalla singola registrazione più "
            "nitida. Tempo di parola, non influenza."
        ),
        "across_all_tables": "In tutti i tavoli",
        "table_detail": "Dettaglio per tavolo",
        "table": "Tavolo {number}",
        "no_findings_yet": "Ancora nessun risultato per questo turno.",
        "draft_not_reviewed": "BOZZA — non ancora revisionata",
        "draft_badge": "bozza — non revisionata",
        "mentioned_at_tables": "Menzionato in {count} tavoli",
        "mentioned_at_one_table": "Menzionato in {count} tavolo",
        "speaker": "Partecipante",
        "evidence_removed": "Prove rimosse con la trascrizione.",
        "type_plural.proposal": "Proposte",
        "type_plural.agreement": "Punti di consenso",
        "type_plural.disagreement": "Punti di divergenza",
        "type_plural.concern": "Preoccupazioni emerse",
        "type_plural.question": "Domande aperte",
        "type_plural.minority_position": "Posizioni di minoranza",
        "type_plural.new_idea": "Idee emergenti",
        "type_plural.other": "Altri risultati",
        "type_singular.proposal": "Proposta",
        "type_singular.agreement": "Punto di consenso",
        "type_singular.disagreement": "Punto di divergenza",
        "type_singular.concern": "Preoccupazione",
        "type_singular.question": "Domanda aperta",
        "type_singular.minority_position": "Posizione di minoranza",
        "type_singular.new_idea": "Idea emergente",
        "date_format": "{day} {month} {year}",
        **_months(_MONTHS_IT),
    },
    # Headings and notes for these three fall back to English until someone
    # who writes the language well fills them in; only the date is native.
    "de": {"date_format": "{day}. {month} {year}", **_months(_MONTHS_DE)},
    "fr": {"date_format": "{day} {month} {year}", **_months(_MONTHS_FR)},
    "es": {"date_format": "{day} de {month} de {year}", **_months(_MONTHS_ES)},
}

DEFAULT_LANGUAGE = "en"


def normalize_language(language: str | None) -> str:
    """The catalogue code for an assembly language: "it", "it-IT" and "IT"
    all read the Italian catalogue; anything unknown reads English."""
    code = (language or "").strip().lower().replace("_", "-").split("-")[0]
    return code if code in CATALOGUE else DEFAULT_LANGUAGE


def text(language: str | None, key: str, **fmt) -> str:
    """The wording for `key` in `language`, English when the language has no
    entry for it. An unknown key is a programming error and raises KeyError."""
    template = CATALOGUE[normalize_language(language)].get(key)
    if template is None:
        template = CATALOGUE[DEFAULT_LANGUAGE][key]
    return template.format(**fmt) if fmt else template


def finding_type_label(language: str | None, type_: str, plural: bool = False) -> str:
    """The label for a finding type; a type the vocabulary does not know is
    shown as its raw value rather than hidden."""
    prefix = "type_plural" if plural else "type_singular"
    try:
        return text(language, f"{prefix}.{type_}")
    except KeyError:
        return type_


def type_labels(language: str | None) -> dict[str, str]:
    """Plural labels by type, in report order."""
    return {type_: finding_type_label(language, type_, plural=True) for type_ in TYPE_ORDER}


def type_labels_singular(language: str | None) -> dict[str, str]:
    """Singular labels by type, in report order."""
    return {type_: finding_type_label(language, type_) for type_ in TYPE_ORDER}


def month_name(language: str | None, month: int) -> str:
    """The name of month 1..12 as it is written in `language`."""
    return text(language, f"month.{month}")


def format_date(language: str | None, when: date) -> str:
    """A date as the language writes it in running text: "18 September 2026",
    "18 settembre 2026", "18. September 2026", "18 de septiembre de 2026"."""
    return text(
        language, "date_format",
        day=when.day, month=month_name(language, when.month), year=when.year,
    )
