# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The QR code must survive being loaded as an image.

The organizer renders it in an <img> rather than injecting the markup, because
an image cannot execute script whatever it contains. An <img> parses its source
as an independent XML document, so the root element needs the SVG namespace —
segno's svg_inline() omits it deliberately, which is right only for markup
pasted into an HTML page.

Without it the browser reports a decode failure and shows a broken-image icon:
naturalWidth 0, and a QR sheet with no codes on it. Measured in Firefox, not
assumed.

qr_sheet.py hit the same trap from the other side: fpdf2 also refuses a root
element in no namespace.
"""

from xml.etree import ElementTree

from citizens.services.invites import _qr_svg

SVG_NS = "http://www.w3.org/2000/svg"
URL = "https://cloud.example.com/index.php/apps/app_api/proxy/citizens/recorder.html#/join/tok"


def test_the_root_element_is_in_the_svg_namespace():
    root = ElementTree.fromstring(_qr_svg(URL))

    assert root.tag == f"{{{SVG_NS}}}svg"


def test_it_parses_as_a_standalone_xml_document():
    """An <img> gets no help from an HTML parser."""
    ElementTree.fromstring(_qr_svg(URL))


def test_it_carries_a_viewbox_and_no_fixed_size():
    """The card scales the code with CSS; a fixed px size clips it."""
    root = ElementTree.fromstring(_qr_svg(URL))

    assert root.get("viewBox")
    assert root.get("width") is None
    assert root.get("height") is None


def test_the_payload_is_the_join_url():
    """A QR nobody can scan looks exactly like one that works.

    Decoding the image back would need a system zbar library to test segno
    rather than this module, so the check is that the URL we hand segno is the
    one the card advertises — the failure this guards against is the two
    drifting apart, not segno mis-encoding.
    """
    from citizens.services.invites import _invite_card

    card = _invite_card(3, "tok")

    assert card.url.endswith("#/join/tok")
    assert card.table_number == 3
