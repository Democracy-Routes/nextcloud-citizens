# Pseudonyms and names never reaching the model

Speaker labels are anonymous (`SPEAKER_01`, never a name), but people say each other's names out loud, and the
transcript records what was said. Citizens therefore masks listed names in the text that is sent to an analysis model.

## What is replaced

Under *Assembly details* an organizer lists names to be replaced with "Person A", "Person B" and so on before the
transcript is sent. Any imported participant's name is included automatically.

* One stable label per **person** for the whole assembly, so the model can still follow who is being referred to
  across a transcript. An entry is one person: "Giulia Rossi" is one label, and "Giulia", "Rossi" and "Giulia Rossi"
  in the text all become it. (Before 0.7 each part got a label of its own.)
* Names shorter than three characters are not replaced, because they match too much ordinary text.
* The labels are letters first (`[Person A]`), so a finding reads as referring to a person.

## What is kept

**Redact what is sent, keep what is stored.** The transcript on this server is unchanged: it is the record and the
source of the report's quotes. Only the copy composed into the prompt is masked. So a finding the model writes says
"[Person A]", while the evidence beneath it still shows what the table actually said.

## Where the same list is used

* The analysis prompts.
* The AI facilitator, which receives the last 40 or so live caption lines of a table with every known participant
  name replaced by a pseudonym.
* The Polis seeds Why panel shows the transcript excerpt with names masked.

## Limits to state in your own privacy information

!!! warning "The list comes from the organizer, not from a detector"
    A name nobody listed is not replaced, and no attempt is made to guess: a list of common first names would mangle
    ordinary words. A list the organizer controls is predictable.

!!! warning "It protects the analysis step only"
    The audio sent for transcription carries names as spoken. If that matters, run a self-hosted engine (Vosk or a
    local Whisper) and nothing leaves at all.

The transcript kept on this server shows what was actually said, so a quoted passage in a report can still contain a
name. If that is unacceptable, withhold quotations (the optional consent box) or review quotes before publishing.
