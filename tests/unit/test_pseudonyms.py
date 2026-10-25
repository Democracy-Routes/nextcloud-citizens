# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Names must not reach the analysis model.

Speaker labels were always anonymous, but people say each other's names out
loud and the transcript records what was said. A real report carried "Simone,
you spoke too much, you should let other people…" — a named criticism of a
participant, printed and sent to an outside service.
"""

from citizens.services.pseudonyms import labels_for, redact


def _map(*names: str) -> dict[str, str]:
    labels = [f"[Person {chr(ord('A') + i)}]" for i in range(len(names))]
    return dict(zip(sorted(names, key=len, reverse=True), labels, strict=True))


def test_a_spoken_name_is_replaced():
    mapping = _map("Simone")

    assert redact("Simone, you spoke too much", mapping) == "[Person A], you spoke too much"


def test_the_same_person_keeps_the_same_stand_in():
    """A single [NAME] everywhere would destroy the discourse the analysis is
    reading — who agreed with whom stops being recoverable."""
    mapping = _map("Simone", "Alessandro")

    text = redact("Simone agreed with Alessandro, then Simone objected", mapping)

    first = text.split("]")[0] + "]"
    assert text.count(first) == 2
    assert "Simone" not in text and "Alessandro" not in text


def test_matching_ignores_case():
    assert "simone" not in redact("simone said so", _map("Simone")).lower().replace("person", "")


def test_a_longer_name_is_replaced_before_the_short_one_inside_it():
    mapping = _map("Anna Maria", "Anna")

    text = redact("Anna Maria disagreed", mapping)

    assert "Anna" not in text
    assert text.count("[Person") == 1


def test_a_name_inside_another_word_is_left_alone():
    # "Ale" is a name here and an ordinary word elsewhere; whole words only
    assert redact("the alert was late", _map("Ale")) == "the alert was late"


def test_punctuation_around_a_name_survives():
    assert redact("It was Simone's idea.", _map("Simone")) == "It was [Person A]'s idea."


def test_an_empty_map_changes_nothing():
    assert redact("Simone said so", {}) == "Simone said so"


def test_a_full_name_is_one_person_and_each_part_points_at_the_same_label():
    """"Giulia Rossi" registered at a table is one person: the model must see
    one stand-in whether the transcript says her first name, her surname or
    both — before 0.7 each part got its own label and one person read as two."""
    mapping = labels_for(["Giulia Rossi", "Marco", "Anna Maria Bianchi, Luca Verdi"])

    assert mapping["Giulia Rossi"] == mapping["Giulia"] == mapping["Rossi"] == "[Person A]"
    assert mapping["Marco"] == "[Person B]"
    assert mapping["Anna Maria Bianchi"] == mapping["Anna"] == mapping["Maria"] == "[Person C]"
    assert mapping["Luca Verdi"] == mapping["Luca"] == "[Person D]"
    # the full name is replaced as one token, never as two labels
    assert redact("Giulia Rossi agreed with Rossi", mapping) == "[Person A] agreed with [Person A]"
    # longest first in the map, so "Anna Maria Bianchi" never becomes half a label
    assert list(mapping)[0] == "Anna Maria Bianchi"
    # a name seen twice (two participants with the same first name) is one label
    assert labels_for(["Marco Neri", "Marco"])["Marco"] == "[Person A]"
