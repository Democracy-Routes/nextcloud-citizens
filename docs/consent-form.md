<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->

# Participant information notice and consent form

A print-ready notice and consent form for a citizens' assembly recorded with
Citizens, in English and Italian. It is written from what the software
actually does — the phone's own information screen, [privacy.md](privacy.md),
and a configuration with a hosted provider for both transcription and
analysis — so nothing in it promises what the app cannot deliver. Fields in
[brackets] are for the organizer to fill in. It is a template, not legal
advice: have counsel read it if the organizer is a public body, and adapt the
recipients if you use a self-hosted engine (then nothing leaves your server).

**How to use it**

- One form per participant, collected before the first round and kept with
  the assembly's records. The information screen on each table's phone stays
  as the second transparency step: it repeats the engine, the retention and
  the "Person 1 / Person 2" labelling, and lets a whole table decline.
- Fill the retention field with the value actually set on the assembly
  (Settings, or the assembly's own override) — the phone shows the same
  number.
- If anyone ticks "I do not consent", seat them at a table that is not
  recorded, or leave that table's phone on the declined screen.
- Announce the recording aloud at the start and post a sign at the door for
  late arrivals; the software cannot know who was in the room.
- Confirm the "not used for training" sentence against your provider's
  terms or data-processing agreement before printing. Delete it if you
  cannot confirm it.
- The legal basis offered is explicit consent (Art. 6(1)(a) and Art. 9(2)(a)
  GDPR): what people say in a policy debate can reveal political opinions,
  which are special-category data. A public body may have another basis in
  law; counsel decides that, not this template.

---

## English

**INFORMATION NOTICE AND CONSENT**
**Citizens' assembly "[assembly name]" — [date], [venue]**

**Who is responsible for your data.** [Organisation name], [postal address],
[email]. Data protection contact: [name / email].

**What we collect.** During the discussion at your table, a phone records
the audio. From that recording we produce a written transcript and, with the
help of artificial intelligence, a summary of the points raised (proposals,
agreements, concerns, questions, minority views). If you gave your name or
email to take part, we keep it in the participant list; that is optional.

**Why, and on what legal basis.** To document the discussion faithfully and
to produce the assembly's report. The legal basis is your **explicit
consent** (Art. 6(1)(a) and, because what people say in a debate may reveal
political opinions, Art. 9(2)(a) GDPR). You are free not to consent: the
discussion at your table can go on without the phone recording it.

**How it works.**

- The phone at your table records the whole conversation and keeps a copy
  until the end of the day, when it is deleted from the phone.
- The recording is sent once to **Mistral AI (Paris, France, EU)** to be
  turned into text. The written transcript — never the audio — is sent to
  the same provider's AI model to draft the summary. Neither the audio nor
  the text is used to train the provider's models [confirm against the
  provider agreement].
- Speakers are labelled only as "Person 1", "Person 2"…: there is no voice
  recognition, and the recording is not linked to your identity. **Names
  spoken aloud do appear in the transcript** as they were said; the
  organizer replaces listed names before the AI analysis.
- Every AI-produced result is reviewed by a person before anything is
  published. The report states that AI was used.
- The report may contain short anonymous quotations from your table. It is
  shared with participants and may be published by the organizer.

**Where your data is kept.** On the organizer's server at [hosting provider,
country — EU]. Recipients: Mistral AI SAS (transcription and AI analysis,
France); [hosting provider]. No transfer outside the EU [confirm].

**How long.** Audio: deleted [90] days after the assembly closes. Transcript,
summaries and report: kept for [duration / until date] as the record of the
assembly. Participant list: [duration].

**Your rights.** Access, rectification, erasure, restriction, portability,
objection, and **withdrawal of consent at any time** (it does not affect
processing already done). Write to [email]. Because voices are not separated
in the recording, erasure after the session means deleting your table's
recording and transcript on request. You may lodge a complaint with the
supervisory authority (in Italy: Garante per la protezione dei dati
personali, www.garanteprivacy.it).

**Consent** — tick each box you agree with:

☐ I consent to the audio recording and transcription of the discussion at my
  table, and to its AI-assisted analysis as described above.

☐ I consent to short anonymous quotations from my table being included in
  the assembly's report, which may be published.

☐ I do **not** consent. (Tell the organizer: you will be seated at a table
  that is not recorded, or the phone at your table will not record.)

Name (print): ________________________________

Signature: ________________________________  Date: ______________

---

## Italiano

**INFORMATIVA E CONSENSO AL TRATTAMENTO DEI DATI PERSONALI**
**Assemblea dei cittadini "[nome dell'assemblea]" — [data], [luogo]**

**Chi è responsabile dei tuoi dati.** [Nome dell'organizzazione],
[indirizzo], [email]. Contatto per la protezione dei dati: [nome / email].

**Cosa raccogliamo.** Durante la discussione al tuo tavolo, un telefono
registra l'audio. Dalla registrazione produciamo una trascrizione scritta e,
con l'aiuto dell'intelligenza artificiale, una sintesi dei punti emersi
(proposte, accordi, preoccupazioni, domande, posizioni di minoranza). Se hai
fornito nome o email per partecipare, li conserviamo nell'elenco dei
partecipanti; sono facoltativi.

**Perché, e su quale base giuridica.** Per documentare fedelmente la
discussione e produrre il rapporto dell'assemblea. La base giuridica è il tuo
**consenso esplicito** (art. 6, par. 1, lett. a) e, poiché ciò che si dice
in un dibattito può rivelare opinioni politiche, art. 9, par. 2, lett. a)
del GDPR). Sei libero di non acconsentire: la discussione al tuo tavolo può
proseguire senza che il telefono la registri.

**Come funziona.**

- Il telefono al tuo tavolo registra tutta la conversazione e ne conserva
  una copia fino alla fine della giornata, quando viene cancellata dal
  telefono.
- La registrazione viene inviata una volta a **Mistral AI (Parigi, Francia,
  UE)** per essere trasformata in testo. La trascrizione scritta — mai
  l'audio — viene inviata al modello di IA dello stesso fornitore per
  redigere la sintesi. Né l'audio né il testo vengono usati per addestrare i
  modelli del fornitore [verificare nel contratto con il fornitore].
- Chi parla è indicato solo come "Persona 1", "Persona 2"…: non c'è
  riconoscimento vocale e la registrazione non è collegata alla tua
  identità. **I nomi pronunciati ad alta voce compaiono nella trascrizione**
  così come sono stati detti; l'organizzatore sostituisce i nomi indicati
  prima dell'analisi con l'IA.
- Ogni risultato prodotto dall'IA viene revisionato da una persona prima di
  qualsiasi pubblicazione. Il rapporto dichiara l'uso dell'IA.
- Il rapporto può contenere brevi citazioni anonime dal tuo tavolo. Viene
  condiviso con i partecipanti e può essere pubblicato dall'organizzatore.

**Dove sono conservati i tuoi dati.** Sul server dell'organizzatore presso
[fornitore di hosting, paese — UE]. Destinatari: Mistral AI SAS
(trascrizione e analisi con IA, Francia); [fornitore di hosting]. Nessun
trasferimento al di fuori dell'UE [verificare].

**Per quanto tempo.** Audio: cancellato [90] giorni dopo la chiusura
dell'assemblea. Trascrizione, sintesi e rapporto: conservati per [durata /
fino al] come documentazione dell'assemblea. Elenco dei partecipanti:
[durata].

**I tuoi diritti.** Accesso, rettifica, cancellazione, limitazione,
portabilità, opposizione e **revoca del consenso in qualsiasi momento**
(senza pregiudicare i trattamenti già effettuati). Scrivi a [email]. Poiché
le voci non sono separate nella registrazione, la cancellazione dopo la
sessione comporta, su richiesta, l'eliminazione della registrazione e della
trascrizione del tuo tavolo. Puoi proporre reclamo al Garante per la
protezione dei dati personali (www.garanteprivacy.it).

**Consenso** — barra le caselle con cui sei d'accordo:

☐ Acconsento alla registrazione audio e alla trascrizione della discussione
  al mio tavolo e alla sua analisi assistita dall'IA come descritto sopra.

☐ Acconsento all'inserimento di brevi citazioni anonime dal mio tavolo nel
  rapporto dell'assemblea, che potrà essere pubblicato.

☐ **Non** acconsento. (Avvisa l'organizzatore: sarai assegnato a un tavolo
  non registrato, oppure il telefono al tuo tavolo non registrerà.)

Nome (stampatello): ________________________________

Firma: ________________________________  Data: ______________
