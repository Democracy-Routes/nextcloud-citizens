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
        "objective": "Objective",
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
            "Discussion summaries are AI-generated neutral descriptions. "
            "“Mentioned at N tables” describes how many discussion tables raised a topic; "
            "it is not a measure of participant support."
        ),
        # only when at least one finding was approved (report._methodology_note)
        "methodology_reviewed": "Findings were reviewed by a human organizer.",
        "transcript_engines": "Speech-to-text: {engines}.",
        "source_live": "live captions",
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
        "consent_registered_note": (
            "{registered} participants registered individually at the tables against the "
            "recording notice; {consenting} consented to being recorded."
        ),
        "validation_note": (
            "{answered} participants said whether their table's summary reflected the "
            "discussion; {missing} flagged something missing, for the organiser to review."
        ),
        "synthesis_heading": "How the discussion developed",
        "carried_forward": "Carried from one session to the next",
        "speaking_comparison": "Speaking balance across tables",
        "speaking_comparison_caveat": (
            "Each line measures one table on its own; voices are detected, not identified, "
            "and talk-time is an estimate, not a measure of influence."
        ),
        "comparison_col_table": "Table",
        "comparison_col_voices": "Voices",
        "comparison_col_largest": "Largest share",
        "comparison_col_smallest": "Smallest share",
        "comparison_col_ratio": "Ratio",
        # executive summary (PDF)
        "executive_summary": "Executive summary",
        "executive_summary_note": (
            "AI-generated overview of each round across all tables; details and "
            "human-reviewed findings follow."
        ),
        # rounds
        "round": "Session {position}",
        "round_titled": "Session {position} — {title}",
        "ai_summary": "AI summary",
        "speaking_balance": "Speaking balance",
        "recorder_changed_caveat": (
            "The phone recording this table changed during the session; voices cannot "
            "be matched across the parts, so the balance covers the fullest part only."
        ),
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
        "quotations_withheld": (
            "Quotations from this table are withheld: a participant seated here did not "
            "consent to being quoted."
        ),
        "quotations_withheld_note": (
            "Verbatim quotations are withheld from tables where a seated participant did not "
            "consent to being quoted; the findings of those tables stand on the analysis alone."
        ),
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
        "objective": "Obiettivo",
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
            "Le sintesi delle discussioni sono descrizioni neutrali generate dall'IA. "
            "«Menzionato in N tavoli» indica in quanti tavoli di discussione è emerso "
            "un tema; non è una misura del sostegno dei partecipanti."
        ),
        "methodology_reviewed": "I risultati sono stati revisionati da un organizzatore.",
        "transcript_engines": "Trascrizione automatica: {engines}.",
        "source_live": "sottotitoli in tempo reale",
        "live_transcript_note": (
            "Le trascrizioni di questa assemblea provengono dai sottotitoli in tempo "
            "reale prodotti mentre i tavoli parlavano, non da una trascrizione separata "
            "delle registrazioni complete. I sottotitoli sono generati sotto pressione "
            "di tempo e possono perdere parti di parlato che il motore non è riuscito a "
            "seguire, quindi alcuni passaggi potrebbero mancare o essere meno accurati "
            "dell'audio stesso."
        ),
        "consent_registered_note": (
            "{registered} partecipanti si sono registrati individualmente ai tavoli "
            "rispetto all'informativa sulla registrazione; {consenting} hanno acconsentito "
            "a essere registrati."
        ),
        "validation_note": (
            "{answered} partecipanti hanno detto se la sintesi del loro tavolo rispecchiava "
            "la discussione; {missing} hanno segnalato che manca qualcosa, da rivedere da "
            "parte di chi organizza."
        ),
        "synthesis_heading": "Come si è sviluppata la discussione",
        "carried_forward": "Portato da una sessione alla successiva",
        "speaking_comparison": "Equilibrio di parola tra i tavoli",
        "speaking_comparison_caveat": (
            "Ogni riga misura un tavolo da solo; le voci sono rilevate, non identificate, e "
            "il tempo di parola è una stima, non una misura di influenza."
        ),
        "comparison_col_table": "Tavolo",
        "comparison_col_voices": "Voci",
        "comparison_col_largest": "Quota maggiore",
        "comparison_col_smallest": "Quota minore",
        "comparison_col_ratio": "Rapporto",
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
        "round": "Sessione {position}",
        "round_titled": "Sessione {position} — {title}",
        "ai_summary": "Sintesi IA",
        "speaking_balance": "Equilibrio degli interventi",
        "recorder_changed_caveat": (
            "Il telefono che registrava questo tavolo è cambiato durante la sessione; le "
            "voci non possono essere abbinate tra le parti, quindi l'equilibrio riguarda "
            "solo la parte più completa."
        ),
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
        "quotations_withheld": (
            "Le citazioni di questo tavolo non sono incluse: un partecipante seduto qui non ha "
            "acconsentito a essere citato."
        ),
        "quotations_withheld_note": (
            "Le citazioni testuali sono omesse per i tavoli in cui un partecipante seduto non ha "
            "acconsentito a essere citato; i risultati di quei tavoli si basano sulla sola analisi."
        ),
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
    "de": {
        "assembly_report": "Bericht der Versammlung",
        "final_report": "ABSCHLUSSBERICHT",
        "closed_on": "geschlossen am {date}",
        "interim_report": "ZWISCHENBERICHT",
        "tables_completed_all_rounds": (
            "{complete} von {expected} Tischen haben alle Runden abgeschlossen"
        ),
        "tables_contributing": "Beitragende Tische: {contributed} von {expected}",
        "participants": "Teilnehmende: {count} (erwartet {expected})",
        "tables": "Tische: {count}",
        "language": "Sprache: {code}",
        "objective": "Ziel",
        "participants_expected": "{count} Teilnehmende (erwartet {expected})",
        "tables_count": "{count} Tische",
        "tables_contributed_to_report": (
            "{contributed} von {expected} Tischen haben zu diesem Bericht beigetragen"
        ),
        "method_heading": "Methode",
        "method": (
            "Bürgerversammlung in Präsenz: Die Teilnehmenden diskutierten an kleinen Tischen; "
            "ein Telefon an jedem Tisch nahm das Gespräch auf, das tischweise transkribiert und "
            "analysiert und anschließend über alle Tische hinweg zusammengeführt wurde."
        ),
        "method_diarized": (
            "Bürgerversammlung in Präsenz: Die Teilnehmenden diskutierten an kleinen Tischen; "
            "ein Telefon an jedem Tisch nahm das Gespräch auf, das mit Sprechertrennung "
            "transkribiert, tischweise analysiert und anschließend über alle Tische hinweg "
            "zusammengeführt wurde."
        ),
        "methodology_note": (
            "KI wurde zur Unterstützung von Transkription und Analyse eingesetzt. "
            "Die Zusammenfassungen der Diskussionen sind von der KI erstellte neutrale "
            "Beschreibungen. „An N Tischen erwähnt“ gibt an, an wie vielen Diskussionstischen "
            "ein Thema angesprochen wurde; es ist kein Maß für die Unterstützung durch die "
            "Teilnehmenden."
        ),
        "methodology_reviewed": "Die Ergebnisse wurden von einer organisierenden Person geprüft.",
        "transcript_engines": "Spracherkennung: {engines}.",
        "source_live": "Live-Untertitel",
        "live_transcript_note": (
            "Die Transkripte dieser Versammlung stammen aus den Live-Untertiteln, die entstanden, "
            "während an den Tischen gesprochen wurde, und nicht aus einer separaten Transkription "
            "der vollständigen Aufnahmen. Untertitel entstehen unter Zeitdruck und können Gesprochenes "
            "auslassen, dem die Engine nicht folgen konnte; daher können Passagen fehlen oder "
            "weniger genau sein als der Ton selbst."
        ),
        "device_replaced_note": (
            "Das Telefon mindestens eines Tisches fiel während einer Runde aus, und die Diskussion "
            "wurde auf einem anderen Gerät fortgesetzt. Beide Teile wurden gemeinsam als ein "
            "Gespräch transkribiert und analysiert; ein kurzer Abschnitt dazwischen wurde nicht "
            "aufgenommen."
        ),
        "consent_registered_note": (
            "{registered} Teilnehmende haben sich an den Tischen einzeln anhand der "
            "Aufnahmeinformation registriert; {consenting} haben der Aufnahme zugestimmt."
        ),
        "validation_note": (
            "{answered} Teilnehmende haben angegeben, ob die Zusammenfassung ihres Tisches die "
            "Diskussion wiedergab; {missing} haben darauf hingewiesen, dass etwas fehlt, zur "
            "Prüfung durch die Organisation."
        ),
        "synthesis_heading": "Wie sich die Diskussion entwickelt hat",
        "carried_forward": "Von einer Sitzung in die nächste übernommen",
        "speaking_comparison": "Redeanteile im Vergleich der Tische",
        "speaking_comparison_caveat": (
            "Jede Zeile misst einen Tisch für sich; Stimmen werden erkannt, nicht identifiziert, "
            "und die Redezeit ist eine Schätzung, kein Maß für Einfluss."
        ),
        "comparison_col_table": "Tisch",
        "comparison_col_voices": "Stimmen",
        "comparison_col_largest": "Größter Anteil",
        "comparison_col_smallest": "Kleinster Anteil",
        "comparison_col_ratio": "Verhältnis",
        "executive_summary": "Zusammenfassung für die Leitung",
        "executive_summary_note": (
            "Von der KI erstellter Überblick über jede Runde an allen Tischen; es folgen die "
            "Einzelheiten und die von Menschen geprüften Ergebnisse."
        ),
        "round": "Sitzung {position}",
        "round_titled": "Sitzung {position} — {title}",
        "ai_summary": "KI-Zusammenfassung",
        "speaking_balance": "Verteilung der Redebeiträge",
        "recorder_changed_caveat": (
            "Das Telefon, das diesen Tisch aufnahm, wurde während der Sitzung gewechselt; Stimmen "
            "lassen sich zwischen den Teilen nicht zuordnen, daher bezieht sich die Verteilung "
            "nur auf den umfangreichsten Teil."
        ),
        "voice": "Stimme {label}",
        "others": "Andere",
        "voices_caveat": (
            "Erkannte Stimmen, nicht namentlich identifiziert — aus der klarsten einzelnen "
            "Aufnahme. Redezeit, nicht Einfluss."
        ),
        "across_all_tables": "Über alle Tische hinweg",
        "table_detail": "Details je Tisch",
        "table": "Tisch {number}",
        "no_findings_yet": "Für diese Runde liegen noch keine Ergebnisse vor.",
        "draft_not_reviewed": "ENTWURF — noch nicht geprüft",
        "draft_badge": "Entwurf — nicht geprüft",
        "mentioned_at_tables": "An {count} Tischen erwähnt",
        "mentioned_at_one_table": "An {count} Tisch erwähnt",
        "speaker": "Teilnehmende Person",
        "evidence_removed": "Belege wurden mit dem Transkript entfernt.",
        "quotations_withheld": (
            "Zitate von diesem Tisch werden nicht wiedergegeben: Eine hier sitzende teilnehmende "
            "Person hat nicht zugestimmt, zitiert zu werden."
        ),
        "quotations_withheld_note": (
            "Wörtliche Zitate werden für Tische zurückgehalten, an denen eine sitzende teilnehmende "
            "Person nicht zugestimmt hat, zitiert zu werden; die Ergebnisse dieser Tische beruhen "
            "allein auf der Analyse."
        ),
        "type_plural.proposal": "Vorschläge",
        "type_plural.agreement": "Konsenspunkte",
        "type_plural.disagreement": "Divergenzpunkte",
        "type_plural.concern": "Geäußerte Bedenken",
        "type_plural.question": "Offene Fragen",
        "type_plural.minority_position": "Minderheitenpositionen",
        "type_plural.new_idea": "Aufkommende Ideen",
        "type_plural.other": "Weitere Ergebnisse",
        "type_singular.proposal": "Vorschlag",
        "type_singular.agreement": "Konsenspunkt",
        "type_singular.disagreement": "Divergenzpunkt",
        "type_singular.concern": "Bedenken",
        "type_singular.question": "Offene Frage",
        "type_singular.minority_position": "Minderheitenposition",
        "type_singular.new_idea": "Aufkommende Idee",
        "date_format": "{day}. {month} {year}",
        **_months(_MONTHS_DE),
    },
    "fr": {
        "assembly_report": "Rapport de l'assemblée",
        "final_report": "RAPPORT FINAL",
        "closed_on": "clôturée le {date}",
        "interim_report": "RAPPORT INTERMÉDIAIRE",
        "tables_completed_all_rounds": (
            "{complete} tables sur {expected} ont terminé tous les tours"
        ),
        "tables_contributing": "Tables contributrices : {contributed} sur {expected}",
        "participants": "Participants : {count} (attendus : {expected})",
        "tables": "Tables : {count}",
        "language": "Langue : {code}",
        "objective": "Objectif",
        "participants_expected": "{count} participants (attendus : {expected})",
        "tables_count": "{count} tables",
        "tables_contributed_to_report": (
            "{contributed} tables sur {expected} ont contribué à ce rapport"
        ),
        "method_heading": "Méthode",
        "method": (
            "Assemblée citoyenne en présentiel : les participants ont discuté en petites tables ; "
            "un téléphone à chaque table a enregistré la conversation, qui a été transcrite et "
            "analysée table par table, puis agrégée sur l'ensemble des tables."
        ),
        "method_diarized": (
            "Assemblée citoyenne en présentiel : les participants ont discuté en petites tables ; "
            "un téléphone à chaque table a enregistré la conversation, qui a été transcrite avec "
            "distinction des locuteurs et analysée table par table, puis agrégée sur l'ensemble "
            "des tables."
        ),
        "methodology_note": (
            "L'IA a été utilisée pour assister la transcription et l'analyse. "
            "Les synthèses des discussions sont des descriptions neutres générées par l'IA. "
            "« Mentionné à N tables » indique à combien de tables de discussion un sujet a été "
            "soulevé ; ce n'est pas une mesure du soutien des participants."
        ),
        "methodology_reviewed": "Les résultats ont été relus par une personne de l'organisation.",
        "transcript_engines": "Reconnaissance vocale : {engines}.",
        "source_live": "sous-titres en direct",
        "live_transcript_note": (
            "Les transcriptions de cette assemblée proviennent des sous-titres en direct produits "
            "pendant que les tables parlaient, et non d'une transcription distincte des "
            "enregistrements complets. Les sous-titres sont produits dans l'urgence et peuvent "
            "manquer des paroles que le moteur n'a pas pu suivre ; des passages peuvent donc "
            "être absents ou moins exacts que le son lui-même."
        ),
        "device_replaced_note": (
            "Le téléphone d'au moins une table a cessé de fonctionner pendant un tour et la "
            "discussion s'est poursuivie sur un autre appareil. Les deux parties ont été "
            "transcrites et analysées ensemble comme une seule conversation ; un court intervalle "
            "entre les deux n'a pas été enregistré."
        ),
        "consent_registered_note": (
            "{registered} participants se sont inscrits individuellement aux tables au regard de "
            "l'information sur l'enregistrement ; {consenting} ont consenti à être enregistrés."
        ),
        "validation_note": (
            "{answered} participants ont indiqué si la synthèse de leur table reflétait la "
            "discussion ; {missing} ont signalé qu'il manquait quelque chose, à examiner par "
            "l'organisation."
        ),
        "synthesis_heading": "Comment la discussion a évolué",
        "carried_forward": "Reporté d'une session à la suivante",
        "speaking_comparison": "Équilibre de la parole entre les tables",
        "speaking_comparison_caveat": (
            "Chaque ligne mesure une table isolément ; les voix sont détectées, non identifiées, "
            "et le temps de parole est une estimation, non une mesure d'influence."
        ),
        "comparison_col_table": "Table",
        "comparison_col_voices": "Voix",
        "comparison_col_largest": "Part la plus grande",
        "comparison_col_smallest": "Part la plus petite",
        "comparison_col_ratio": "Rapport",
        "executive_summary": "Synthèse exécutive",
        "executive_summary_note": (
            "Aperçu généré par l'IA de chaque tour sur l'ensemble des tables ; les détails et les "
            "résultats relus par une personne suivent."
        ),
        "round": "Session {position}",
        "round_titled": "Session {position} — {title}",
        "ai_summary": "Synthèse de l'IA",
        "speaking_balance": "Répartition de la parole",
        "recorder_changed_caveat": (
            "Le téléphone qui enregistrait cette table a changé pendant la session ; les voix ne "
            "peuvent pas être rapprochées d'une partie à l'autre, la répartition ne porte donc "
            "que sur la partie la plus complète."
        ),
        "voice": "Voix {label}",
        "others": "Autres",
        "voices_caveat": (
            "Voix détectées, non identifiées par leur nom — à partir de l'enregistrement unique "
            "le plus net. Temps de parole, non influence."
        ),
        "across_all_tables": "Sur l'ensemble des tables",
        "table_detail": "Détail par table",
        "table": "Table {number}",
        "no_findings_yet": "Aucun résultat pour ce tour pour le moment.",
        "draft_not_reviewed": "BROUILLON — pas encore relu",
        "draft_badge": "brouillon — non relu",
        "mentioned_at_tables": "Mentionné à {count} tables",
        "mentioned_at_one_table": "Mentionné à {count} table",
        "speaker": "Participant",
        "evidence_removed": "Éléments de preuve supprimés avec la transcription.",
        "quotations_withheld": (
            "Les citations de cette table ne sont pas reproduites : un participant assis ici n'a "
            "pas consenti à être cité."
        ),
        "quotations_withheld_note": (
            "Les citations textuelles sont omises pour les tables où un participant assis n'a pas "
            "consenti à être cité ; les résultats de ces tables reposent sur la seule analyse."
        ),
        "type_plural.proposal": "Propositions",
        "type_plural.agreement": "Points de consensus",
        "type_plural.disagreement": "Points de divergence",
        "type_plural.concern": "Préoccupations exprimées",
        "type_plural.question": "Questions ouvertes",
        "type_plural.minority_position": "Positions minoritaires",
        "type_plural.new_idea": "Idées émergentes",
        "type_plural.other": "Autres résultats",
        "type_singular.proposal": "Proposition",
        "type_singular.agreement": "Point de consensus",
        "type_singular.disagreement": "Point de divergence",
        "type_singular.concern": "Préoccupation",
        "type_singular.question": "Question ouverte",
        "type_singular.minority_position": "Position minoritaire",
        "type_singular.new_idea": "Idée émergente",
        "date_format": "{day} {month} {year}",
        **_months(_MONTHS_FR),
    },
    "es": {
        "assembly_report": "Informe de la asamblea",
        "final_report": "INFORME FINAL",
        "closed_on": "cerrada el {date}",
        "interim_report": "INFORME PROVISIONAL",
        "tables_completed_all_rounds": (
            "{complete} de {expected} mesas han completado todas las rondas"
        ),
        "tables_contributing": "Mesas que han contribuido: {contributed} de {expected}",
        "participants": "Participantes: {count} (previstos {expected})",
        "tables": "Mesas: {count}",
        "language": "Idioma: {code}",
        "objective": "Objetivo",
        "participants_expected": "{count} participantes (previstos {expected})",
        "tables_count": "{count} mesas",
        "tables_contributed_to_report": (
            "{contributed} de {expected} mesas han contribuido a este informe"
        ),
        "method_heading": "Método",
        "method": (
            "Asamblea ciudadana presencial: los participantes debatieron en mesas pequeñas; "
            "un teléfono en cada mesa grabó la conversación, que se transcribió y analizó mesa "
            "por mesa y después se agregó entre todas las mesas."
        ),
        "method_diarized": (
            "Asamblea ciudadana presencial: los participantes debatieron en mesas pequeñas; "
            "un teléfono en cada mesa grabó la conversación, que se transcribió con distinción "
            "de voces y se analizó mesa por mesa, y después se agregó entre todas las mesas."
        ),
        "methodology_note": (
            "Se usó IA como apoyo para la transcripción y el análisis. "
            "Los resúmenes de las discusiones son descripciones neutrales generadas por IA. "
            "«Mencionado en N mesas» indica en cuántas mesas de discusión se planteó un tema; "
            "no es una medida del apoyo de los participantes."
        ),
        "methodology_reviewed": "Los resultados fueron revisados por una persona de la organización.",
        "transcript_engines": "Reconocimiento de voz: {engines}.",
        "source_live": "subtítulos en directo",
        "live_transcript_note": (
            "Las transcripciones de esta asamblea proceden de los subtítulos en directo "
            "producidos mientras las mesas hablaban, no de una transcripción independiente de las "
            "grabaciones completas. Los subtítulos se generan con presión de tiempo y pueden "
            "omitir habla que el motor no logró seguir, por lo que algunos pasajes pueden faltar "
            "o ser menos precisos que el propio audio."
        ),
        "device_replaced_note": (
            "El teléfono de al menos una mesa dejó de funcionar durante una ronda y la discusión "
            "continuó en otro dispositivo. Ambas partes se transcribieron y analizaron juntas como "
            "una sola conversación; un breve tramo entre las dos no se grabó."
        ),
        "consent_registered_note": (
            "{registered} participantes se registraron individualmente en las mesas conforme al "
            "aviso de grabación; {consenting} consintieron ser grabados."
        ),
        "validation_note": (
            "{answered} participantes indicaron si el resumen de su mesa reflejaba la discusión; "
            "{missing} señalaron que faltaba algo, para que la organización lo revise."
        ),
        "synthesis_heading": "Cómo se desarrolló la discusión",
        "carried_forward": "Trasladado de una sesión a la siguiente",
        "speaking_comparison": "Equilibrio de intervenciones entre mesas",
        "speaking_comparison_caveat": (
            "Cada línea mide una mesa por sí sola; las voces se detectan, no se identifican, y "
            "el tiempo de palabra es una estimación, no una medida de influencia."
        ),
        "comparison_col_table": "Mesa",
        "comparison_col_voices": "Voces",
        "comparison_col_largest": "Mayor proporción",
        "comparison_col_smallest": "Menor proporción",
        "comparison_col_ratio": "Relación",
        "executive_summary": "Resumen ejecutivo",
        "executive_summary_note": (
            "Panorama generado por IA de cada ronda en todas las mesas; a continuación se "
            "presentan los detalles y los resultados revisados por una persona."
        ),
        "round": "Sesión {position}",
        "round_titled": "Sesión {position} — {title}",
        "ai_summary": "Resumen de la IA",
        "speaking_balance": "Equilibrio de intervenciones",
        "recorder_changed_caveat": (
            "El teléfono que grababa esta mesa cambió durante la sesión; las voces no pueden "
            "emparejarse entre las partes, por lo que el equilibrio abarca solo la parte más "
            "completa."
        ),
        "voice": "Voz {label}",
        "others": "Otros",
        "voices_caveat": (
            "Voces detectadas, no identificadas por nombre — a partir de la grabación individual "
            "más nítida. Tiempo de palabra, no influencia."
        ),
        "across_all_tables": "En todas las mesas",
        "table_detail": "Detalle por mesa",
        "table": "Mesa {number}",
        "no_findings_yet": "Todavía no hay resultados para esta ronda.",
        "draft_not_reviewed": "BORRADOR — aún sin revisar",
        "draft_badge": "borrador — sin revisar",
        "mentioned_at_tables": "Mencionado en {count} mesas",
        "mentioned_at_one_table": "Mencionado en {count} mesa",
        "speaker": "Participante",
        "evidence_removed": "Pruebas eliminadas junto con la transcripción.",
        "quotations_withheld": (
            "No se incluyen citas de esta mesa: un participante sentado aquí no consintió ser "
            "citado."
        ),
        "quotations_withheld_note": (
            "Se omiten las citas textuales de las mesas en las que un participante sentado no "
            "consintió ser citado; los resultados de esas mesas se basan únicamente en el análisis."
        ),
        "type_plural.proposal": "Propuestas",
        "type_plural.agreement": "Puntos de consenso",
        "type_plural.disagreement": "Puntos de divergencia",
        "type_plural.concern": "Preocupaciones planteadas",
        "type_plural.question": "Preguntas abiertas",
        "type_plural.minority_position": "Posiciones minoritarias",
        "type_plural.new_idea": "Ideas emergentes",
        "type_plural.other": "Otros resultados",
        "type_singular.proposal": "Propuesta",
        "type_singular.agreement": "Punto de consenso",
        "type_singular.disagreement": "Punto de divergencia",
        "type_singular.concern": "Preocupación",
        "type_singular.question": "Pregunta abierta",
        "type_singular.minority_position": "Posición minoritaria",
        "type_singular.new_idea": "Idea emergente",
        "date_format": "{day} de {month} de {year}",
        **_months(_MONTHS_ES),
    },
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
