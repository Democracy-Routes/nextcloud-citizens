# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A table's colour follows its number and never carries meaning of its own."""

import pytest

from citizens.domain.tables import TABLE_PALETTE, color_for


def test_the_first_six_tables_take_the_palette_in_order():
    assert [color_for(n) for n in range(1, 7)] == list(TABLE_PALETTE)
    assert TABLE_PALETTE == ("blue", "green", "orange", "purple", "red", "teal")


def test_the_palette_wraps_so_table_seven_is_blue_again():
    assert color_for(7) == "blue"
    assert color_for(13) == "blue"
    assert color_for(12) == "teal"
    assert color_for(200) == color_for(200 % 6 or 6)


@pytest.mark.parametrize("number", [0, -3])
def test_a_nonsensical_number_still_gets_a_colour(number):
    # never a crash in a renderer: the colour is a cue, not a contract
    assert color_for(number) == "blue"
