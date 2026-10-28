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
NOTICE_VERSION = "2026-10.3"

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
        "retention_zero": (
            "How long: the audio recording and the transcript are deleted as soon as the "
            "assembly is closed and its report is written. Only the report — summaries and "
            "quotations — is kept as the record of the assembly, together with the "
            "participant list."
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
        "choice": (
            "Taking part does not require being recorded: if you do not consent, you can sit "
            "at a table that is not recorded."
        ),
        "accept": (
            "By registering you declare that you have read this notice and you consent to the "
            "audio recording of the discussion at your table, to its transcription and "
            "AI-assisted analysis."
        ),
        "accept_quotations": (
            "I also agree to short anonymous quotations from my table being included in the "
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
        "retention_zero": (
            "Per quanto tempo: la registrazione audio e la trascrizione vengono cancellate "
            "appena l'assemblea viene chiusa e il rapporto è scritto. Solo il rapporto — sintesi "
            "e citazioni — è conservato come documentazione dell'assemblea, insieme all'elenco "
            "dei partecipanti."
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
        "choice": (
            "Partecipare non richiede di essere registrati: se non acconsenti, puoi sederti a "
            "un tavolo che non viene registrato."
        ),
        "accept": (
            "Registrandoti dichiari di aver letto questa informativa e acconsenti alla "
            "registrazione audio della discussione al tuo tavolo, alla sua trascrizione e "
            "analisi assistita dall'IA."
        ),
        "accept_quotations": (
            "Acconsento inoltre a che brevi citazioni anonime dal mio tavolo siano inserite nel "
            "rapporto dell'assemblea, che potrà essere pubblicato."
        ),
        "fallback_controller": "L'organizzazione",
    },
    "de": {
        "who": "{controller} nimmt diese Diskussion auf und ist für deine Daten verantwortlich{address}.",
        "who_contact": " Kontakt: {contact}.",
        "who_dpo": " Kontakt für den Datenschutz: {dpo}.",
        "what": (
            "Während der Diskussion an deinem Tisch nimmt das Telefon auf dem Tisch den Ton auf. "
            "Aus dieser Aufnahme erstellen wir ein schriftliches Transkript und, mit Hilfe "
            "künstlicher Intelligenz, eine Zusammenfassung der angesprochenen Punkte (Vorschläge, "
            "Vereinbarungen, Bedenken, Fragen, Minderheitenmeinungen). Der Name, den du bei der "
            "Anmeldung angibst, und die E-Mail-Adresse, falls du eine angeben möchtest, werden in "
            "der Teilnehmerliste gespeichert."
        ),
        "why": (
            "Warum, und auf welcher Rechtsgrundlage: um die Diskussion getreu zu dokumentieren und "
            "den Bericht der Versammlung zu erstellen. Die Rechtsgrundlage ist deine ausdrückliche "
            "Einwilligung (Art. 6 Abs. 1 Buchst. a DSGVO und, weil das, was in einer Debatte gesagt "
            "wird, politische Meinungen offenbaren kann, Art. 9 Abs. 2 Buchst. a DSGVO). Es steht "
            "dir frei, nicht einzuwilligen: Die Diskussion an deinem Tisch kann auch ohne "
            "Aufnahme durch das Telefon weitergehen."
        ),
        "how_phone_purge": (
            "Das Telefon an deinem Tisch behält eine Kopie der Aufnahme, bis der Server sie "
            "erhalten hat; die Kopie wird vom Telefon gelöscht, wenn die Versammlung geschlossen "
            "wird."
        ),
        "how_phone_keep": (
            "Das Telefon an deinem Tisch behält eine Kopie der Aufnahme, bis der Server sie "
            "erhalten hat und die Organisation die Telefone leert."
        ),
        "engine_hosted": (
            "Die Aufnahme wird an {engine} gesendet, einen Dienst außerhalb des eigenen Servers "
            "der Organisation, um in Text umgewandelt zu werden."
        ),
        "engine_local": (
            "Die Aufnahme wird von {engine} auf dem eigenen Server der Organisation transkribiert; "
            "der Ton wird an kein externes Unternehmen gesendet."
        ),
        "engine_none": (
            "Es ist kein Transkriptionsdienst eingerichtet, daher bleibt der Ton auf diesem Server."
        ),
        "analysis_hosted": (
            "Das schriftliche Transkript — niemals der Ton — wird an {provider} gesendet, einen "
            "externen KI-Dienst, um die Zusammenfassung und die Ergebnisse zu entwerfen."
        ),
        "analysis_hosted_unnamed": (
            "Das schriftliche Transkript — niemals der Ton — wird an einen externen KI-Dienst "
            "gesendet, um die Zusammenfassung und die Ergebnisse zu entwerfen."
        ),
        "analysis_local": (
            "Das schriftliche Transkript wird von einem KI-Modell zusammengefasst, das auf dem "
            "eigenen Server der Organisation läuft."
        ),
        "analysis_none": (
            "Es wird keine KI-Analyse durchgeführt; es wird nur das Transkript erstellt."
        ),
        "speakers": (
            "Sprechende werden nur als \"Speaker 1\", \"Speaker 2\" bezeichnet: Es gibt keine "
            "Stimmerkennung, und die Aufnahme ist nicht mit deiner Identität verknüpft. Laut "
            "ausgesprochene Namen erscheinen im Transkript so, wie sie gesagt wurden; die Namen "
            "der gelisteten Teilnehmenden werden durch Pseudonyme ersetzt, bevor irgendein Text "
            "den Server verlässt."
        ),
        "review": (
            "Jedes von der KI erzeugte Ergebnis wird von einer Person geprüft, bevor etwas "
            "veröffentlicht wird, und der Bericht gibt an, dass KI verwendet wurde. Der Bericht "
            "kann kurze anonyme Zitate von deinem Tisch enthalten; er wird mit den Teilnehmenden "
            "geteilt und kann von der Organisation veröffentlicht werden."
        ),
        "where": "Wo deine Daten gespeichert werden: auf dem Server der Organisation{hosting}.{recipients}",
        "where_hosting": " bei {hosting}",
        "where_recipients": " Empfänger: {recipients}.",
        "retention_days": (
            "Wie lange: Die Tonaufnahme wird {days} Tage nach dem Schluss der Versammlung gelöscht. "
            "Das Transkript, die Zusammenfassungen und der Bericht werden zusammen mit der "
            "Teilnehmerliste als Dokumentation der Versammlung aufbewahrt."
        ),
        "retention_none": (
            "Wie lange: Die Tonaufnahme wird aufbewahrt, bis eine organisierende Person sie löscht. "
            "Das Transkript, die Zusammenfassungen und der Bericht werden zusammen mit der "
            "Teilnehmerliste als Dokumentation der Versammlung aufbewahrt."
        ),
        "retention_zero": (
            "Wie lange: Die Tonaufnahme und das Transkript werden gelöscht, sobald die Versammlung "
            "geschlossen und ihr Bericht geschrieben ist. Nur der Bericht — Zusammenfassungen und "
            "Zitate — wird zusammen mit der Teilnehmerliste als Dokumentation der Versammlung "
            "aufbewahrt."
        ),
        "rights": (
            "Deine Rechte: Auskunft, Berichtigung, Löschung, Einschränkung der Verarbeitung, "
            "Datenübertragbarkeit, Widerspruch und jederzeitiger Widerruf der Einwilligung (die "
            "Rechtmäßigkeit der bis dahin erfolgten Verarbeitung bleibt unberührt){contact}. Da die "
            "Stimmen in der Aufnahme nicht getrennt sind, bedeutet eine Löschung nach der Sitzung, "
            "dass auf Anfrage die Aufnahme und das Transkript deines Tisches gelöscht werden. Du "
            "kannst Beschwerde bei {authority} einlegen."
        ),
        "rights_contact": " — schreibe an {contact}",
        "authority_default": "der Datenschutzbehörde deines Landes",
        "choice": (
            "Die Teilnahme setzt nicht voraus, aufgenommen zu werden: Wenn du nicht einwilligst, "
            "kannst du an einem Tisch sitzen, der nicht aufgenommen wird."
        ),
        "accept": (
            "Mit der Anmeldung erklärst du, diese Information gelesen zu haben, und willigst in die "
            "Tonaufnahme der Diskussion an deinem Tisch, in deren Transkription und in die "
            "KI-gestützte Analyse ein."
        ),
        "accept_quotations": (
            "Ich bin außerdem damit einverstanden, dass kurze anonyme Zitate von meinem Tisch in "
            "den Bericht der Versammlung aufgenommen werden, der veröffentlicht werden kann."
        ),
        "fallback_controller": "Die Organisation",
    },
    "fr": {
        "who": "{controller} enregistre cette discussion et est responsable de tes données{address}.",
        "who_contact": " Contact : {contact}.",
        "who_dpo": " Contact pour la protection des données : {dpo}.",
        "what": (
            "Pendant la discussion à ta table, le téléphone posé sur la table enregistre le son. "
            "À partir de cet enregistrement, nous produisons une transcription écrite et, avec "
            "l'aide de l'intelligence artificielle, une synthèse des points soulevés (propositions, "
            "accords, préoccupations, questions, positions minoritaires). Le nom que tu indiques "
            "lors de l'inscription, et l'adresse e-mail si tu choisis d'en donner une, sont "
            "conservés dans la liste des participants."
        ),
        "why": (
            "Pourquoi, et sur quelle base juridique : pour documenter fidèlement la discussion et "
            "produire le rapport de l'assemblée. La base juridique est ton consentement explicite "
            "(art. 6, par. 1, point a) du RGPD et, parce que ce qui est dit dans un débat peut "
            "révéler des opinions politiques, art. 9, par. 2, point a) du RGPD). Tu es libre de ne "
            "pas consentir : la discussion à ta table peut se poursuivre sans que le téléphone "
            "t'enregistre."
        ),
        "how_phone_purge": (
            "Le téléphone à ta table conserve une copie de l'enregistrement jusqu'à ce que le "
            "serveur l'ait reçu ; la copie est supprimée du téléphone à la clôture de "
            "l'assemblée."
        ),
        "how_phone_keep": (
            "Le téléphone à ta table conserve une copie de l'enregistrement jusqu'à ce que le "
            "serveur l'ait reçu et que l'organisation vide les téléphones."
        ),
        "engine_hosted": (
            "L'enregistrement est envoyé à {engine}, un service extérieur au serveur propre de "
            "l'organisation, pour être transformé en texte."
        ),
        "engine_local": (
            "L'enregistrement est transcrit par {engine} sur le serveur propre de l'organisation ; "
            "le son n'est envoyé à aucune entreprise extérieure."
        ),
        "engine_none": (
            "Aucun moteur de transcription n'est configuré, le son reste donc sur ce serveur."
        ),
        "analysis_hosted": (
            "La transcription écrite — jamais le son — est envoyée à {provider}, un service d'IA "
            "extérieur, pour rédiger la synthèse et les conclusions."
        ),
        "analysis_hosted_unnamed": (
            "La transcription écrite — jamais le son — est envoyée à un service d'IA extérieur "
            "pour rédiger la synthèse et les conclusions."
        ),
        "analysis_local": (
            "La transcription écrite est résumée par un modèle d'IA qui fonctionne sur le serveur "
            "propre de l'organisation."
        ),
        "analysis_none": (
            "Aucune analyse par IA n'est effectuée ; seule la transcription est produite."
        ),
        "speakers": (
            "Les personnes qui parlent sont désignées uniquement comme \"Speaker 1\", "
            "\"Speaker 2\" : il n'y a pas de reconnaissance vocale, et l'enregistrement n'est pas "
            "lié à ton identité. Les noms prononcés à voix haute apparaissent dans la "
            "transcription tels qu'ils ont été dits ; les noms des participants inscrits sont "
            "remplacés par des pseudonymes avant que tout texte ne quitte le serveur."
        ),
        "review": (
            "Chaque résultat produit par l'IA est relu par une personne avant toute publication, "
            "et le rapport indique que l'IA a été utilisée. Le rapport peut contenir de courtes "
            "citations anonymes de ta table ; il est partagé avec les participants et peut être "
            "publié par l'organisation."
        ),
        "where": "Où tes données sont conservées : sur le serveur de l'organisation{hosting}.{recipients}",
        "where_hosting": " chez {hosting}",
        "where_recipients": " Destinataires : {recipients}.",
        "retention_days": (
            "Combien de temps : l'enregistrement audio est supprimé {days} jours après la clôture "
            "de l'assemblée. La transcription, les synthèses et le rapport sont conservés comme "
            "documentation de l'assemblée, avec la liste des participants."
        ),
        "retention_none": (
            "Combien de temps : l'enregistrement audio est conservé jusqu'à ce qu'une personne de "
            "l'organisation le supprime. La transcription, les synthèses et le rapport sont "
            "conservés comme documentation de l'assemblée, avec la liste des participants."
        ),
        "retention_zero": (
            "Combien de temps : l'enregistrement audio et la transcription sont supprimés dès que "
            "l'assemblée est clôturée et que son rapport est rédigé. Seul le rapport — synthèses "
            "et citations — est conservé comme documentation de l'assemblée, avec la liste des "
            "participants."
        ),
        "rights": (
            "Tes droits : accès, rectification, effacement, limitation, portabilité, opposition "
            "et retrait du consentement à tout moment (sans remettre en cause les traitements "
            "déjà effectués){contact}. Comme les voix ne sont pas séparées dans "
            "l'enregistrement, l'effacement après la session signifie, sur demande, la "
            "suppression de l'enregistrement et de la transcription de ta table. Tu peux "
            "introduire une réclamation auprès de {authority}."
        ),
        "rights_contact": " — écris à {contact}",
        "authority_default": "l'autorité de protection des données de ton pays",
        "choice": (
            "Participer n'exige pas d'être enregistré : si tu ne consens pas, tu peux t'asseoir "
            "à une table qui n'est pas enregistrée."
        ),
        "accept": (
            "En t'inscrivant, tu déclares avoir lu cette information et tu consens à "
            "l'enregistrement audio de la discussion à ta table, à sa transcription et à son "
            "analyse assistée par l'IA."
        ),
        "accept_quotations": (
            "J'accepte aussi que de courtes citations anonymes de ma table soient incluses dans "
            "le rapport de l'assemblée, qui peut être publié."
        ),
        "fallback_controller": "L'organisation",
    },
    "es": {
        "who": "{controller} graba esta discusión y es responsable de tus datos{address}.",
        "who_contact": " Contacto: {contact}.",
        "who_dpo": " Contacto de protección de datos: {dpo}.",
        "what": (
            "Durante la discusión en tu mesa, el teléfono que está sobre la mesa graba el audio. "
            "A partir de esa grabación producimos una transcripción escrita y, con la ayuda de la "
            "inteligencia artificial, un resumen de los puntos planteados (propuestas, acuerdos, "
            "preocupaciones, preguntas, posiciones minoritarias). El nombre que indicas al "
            "registrarte, y el correo electrónico si decides facilitarlo, se conservan en la "
            "lista de participantes."
        ),
        "why": (
            "Por qué, y con qué base jurídica: para documentar fielmente la discusión y elaborar "
            "el informe de la asamblea. La base jurídica es tu consentimiento explícito "
            "(art. 6.1.a) del RGPD y, porque lo que se dice en un debate puede revelar opiniones "
            "políticas, art. 9.2.a) del RGPD). Eres libre de no consentir: la discusión en tu "
            "mesa puede continuar sin que el teléfono te grabe."
        ),
        "how_phone_purge": (
            "El teléfono de tu mesa conserva una copia de la grabación hasta que el servidor la "
            "haya recibido; la copia se borra del teléfono cuando se cierra la asamblea."
        ),
        "how_phone_keep": (
            "El teléfono de tu mesa conserva una copia de la grabación hasta que el servidor la "
            "haya recibido y la organización vacíe los teléfonos."
        ),
        "engine_hosted": (
            "La grabación se envía a {engine}, un servicio ajeno al servidor propio de la "
            "organización, para convertirla en texto."
        ),
        "engine_local": (
            "La grabación la transcribe {engine} en el servidor propio de la organización; el "
            "audio no se envía a ninguna empresa externa."
        ),
        "engine_none": (
            "No hay ningún motor de transcripción configurado, por lo que el audio se queda en "
            "este servidor."
        ),
        "analysis_hosted": (
            "La transcripción escrita — nunca el audio — se envía a {provider}, un servicio de IA "
            "externo, para redactar el resumen y las conclusiones."
        ),
        "analysis_hosted_unnamed": (
            "La transcripción escrita — nunca el audio — se envía a un servicio de IA externo "
            "para redactar el resumen y las conclusiones."
        ),
        "analysis_local": (
            "La transcripción escrita la resume un modelo de IA que se ejecuta en el servidor "
            "propio de la organización."
        ),
        "analysis_none": (
            "No se realiza ningún análisis con IA; solo se produce la transcripción."
        ),
        "speakers": (
            "Quienes hablan se identifican solo como \"Speaker 1\", \"Speaker 2\": no hay "
            "reconocimiento de voz y la grabación no está vinculada a tu identidad. Los nombres "
            "dichos en voz alta aparecen en la transcripción tal como se dijeron; los nombres de "
            "los participantes registrados se sustituyen por seudónimos antes de que cualquier "
            "texto salga del servidor."
        ),
        "review": (
            "Todo resultado producido por la IA es revisado por una persona antes de publicar "
            "nada, y el informe indica que se usó IA. El informe puede contener citas breves y "
            "anónimas de tu mesa; se comparte con los participantes y la organización puede "
            "publicarlo."
        ),
        "where": "Dónde se conservan tus datos: en el servidor de la organización{hosting}.{recipients}",
        "where_hosting": " en {hosting}",
        "where_recipients": " Destinatarios: {recipients}.",
        "retention_days": (
            "Durante cuánto tiempo: la grabación de audio se borra {days} días después del cierre "
            "de la asamblea. La transcripción, los resúmenes y el informe se conservan como "
            "documentación de la asamblea, junto con la lista de participantes."
        ),
        "retention_none": (
            "Durante cuánto tiempo: la grabación de audio se conserva hasta que una persona de la "
            "organización la borre. La transcripción, los resúmenes y el informe se conservan "
            "como documentación de la asamblea, junto con la lista de participantes."
        ),
        "retention_zero": (
            "Durante cuánto tiempo: la grabación de audio y la transcripción se borran en cuanto "
            "se cierra la asamblea y se redacta su informe. Solo el informe — resúmenes y "
            "citas — se conserva como documentación de la asamblea, junto con la lista de "
            "participantes."
        ),
        "rights": (
            "Tus derechos: acceso, rectificación, supresión, limitación, portabilidad, oposición "
            "y retirada del consentimiento en cualquier momento (sin que ello afecte a los "
            "tratamientos ya realizados){contact}. Como las voces no están separadas en la "
            "grabación, la supresión después de la sesión supone, a petición tuya, borrar la "
            "grabación y la transcripción de tu mesa. Puedes presentar una reclamación ante "
            "{authority}."
        ),
        "rights_contact": " — escribe a {contact}",
        "authority_default": "la autoridad de protección de datos de tu país",
        "choice": (
            "Participar no exige que te graben: si no consientes, puedes sentarte en una mesa "
            "que no se graba."
        ),
        "accept": (
            "Al registrarte declaras que has leído este aviso y consientes la grabación de audio "
            "de la discusión en tu mesa, su transcripción y su análisis asistido por IA."
        ),
        "accept_quotations": (
            "También acepto que citas breves y anónimas de mi mesa se incluyan en el informe de "
            "la asamblea, que puede ser publicado."
        ),
        "fallback_controller": "La organización",
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
        """The sentence the required box carries: recording, transcription,
        analysis — the processing. Second to last paragraph since 2026-10.3."""
        return self.paragraphs[-2]

    @property
    def acceptance_quotations(self) -> str:
        """The sentence the optional box carries: short anonymous quotations in
        the report. Last paragraph. Declining it withholds every verbatim
        quotation from the person's table, not only their own words, because
        voices are not separated in the recording."""
        return self.paragraphs[-1]

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "language": self.language,
            "hash": self.hash,
            "paragraphs": list(self.paragraphs),
            "acceptance": self.acceptance,
            "acceptance_quotations": self.acceptance_quotations,
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
    if handling.get("zero_retention"):
        paragraphs.append(t("retention_zero"))
    else:
        paragraphs.append(t("retention_days", days=days) if days > 0 else t("retention_none"))
    paragraphs.append(
        t(
            "rights",
            contact=t("rights_contact", contact=contact) if contact else "",
            authority=authority,
        )
    )
    paragraphs.append(t("choice"))
    paragraphs.append(t("accept"))
    paragraphs.append(t("accept_quotations"))
    return Notice(NOTICE_VERSION, lang, notice_hash(NOTICE_VERSION, lang, paragraphs), paragraphs)
