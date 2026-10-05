# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A table's visual identity: its number, and a colour derived from it.

The number is the identity — unique within the assembly, printed on the QR
sheet, carried by every phone and every recording. The colour is only a
second cue for a room full of people looking for "the blue table"; it is
assigned automatically, repeats after six tables, and nothing may depend on it
for correctness.
"""

TABLE_PALETTE = ("blue", "green", "orange", "purple", "red", "teal")


def color_for(number: int) -> str:
    """Table 1 is blue, 6 teal, 7 blue again."""
    return TABLE_PALETTE[(max(number, 1) - 1) % len(TABLE_PALETTE)]
