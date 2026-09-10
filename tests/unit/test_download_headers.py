# SPDX-License-Identifier: AGPL-3.0-or-later
from urllib.parse import quote

import pytest
from starlette.responses import Response

from citizens.api.downloads import NO_STORE, download_headers


@pytest.mark.parametrize("filename", ["Città.pdf", "市民 🗳️.pdf", 'quote"\r\nname.pdf'])
def test_download_names_are_valid_headers(filename):
    response = Response(b"pdf", headers=download_headers(filename))
    disposition = response.headers["content-disposition"]
    assert disposition.isascii()
    assert "\r" not in disposition and "\n" not in disposition
    assert "filename*=UTF-8''" in disposition
    assert quote(filename.replace("\r", "").replace("\n", ""), safe="") in disposition
    assert response.headers["cache-control"] == NO_STORE
