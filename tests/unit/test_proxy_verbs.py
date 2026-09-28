# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every route must use an HTTP verb the AppAPI proxy can actually forward.

AppAPI publishes proxy handlers for GET, POST, PUT and DELETE only
(ExAppProxy#ExAppGet/Post/Put/Delete in app_api/appinfo/routes.php). A PATCH
to /apps/app_api/proxy/citizens/... is answered 405 by Nextcloud's own router:
it never reaches this app, and our <routes> table is never consulted.

Finding review (Approve/Reject) shipped broken for exactly that reason, and the
rest of the suite cannot see this class of bug — TestClient talks to FastAPI
directly, so it bypasses the proxy that does the rejecting.

Routes come from app.openapi() rather than app.routes: since FastAPI 0.141
app.routes holds unexpanded _IncludedRouter placeholders, so walking it finds
no endpoints at all and every assertion here would pass vacuously.
"""

import pathlib
import re
import xml.etree.ElementTree as ElementTree

import pytest

from citizens.main import create_app

ROOT = pathlib.Path(__file__).resolve().parents[2]

PROXYABLE = {"GET", "POST", "PUT", "DELETE"}


@pytest.fixture(scope="module")
def routes() -> list[tuple[str, str]]:
    """(path, METHOD) for the user-facing API. /heartbeat, /init and /enabled
    are AppAPI's own callbacks and do not travel through the user proxy."""
    paths = create_app(with_auth=False).openapi()["paths"]
    found = [
        (path, method.upper())
        for path, operations in paths.items()
        for method in operations
        if path.startswith("/api/v1/") or path.startswith("/recorder")
    ]
    # the placeholder trap above: if the inventory ever comes back empty or
    # missing a route we know exists, these tests are not testing anything
    assert len(found) > 40, f"route inventory looks wrong: {len(found)} routes"
    assert any(path == "/api/v1/findings/{finding_id}" for path, _ in found)
    return found


def _declared_routes() -> list[tuple[str, set[str]]]:
    root = ElementTree.parse(ROOT / "appinfo" / "info.xml").getroot()
    return [
        (
            route.findtext("url", ""),
            {verb.strip().upper() for verb in route.findtext("verb", "").split(",")},
        )
        for route in root.findall("external-app/routes/route")
    ]


def test_no_route_uses_a_verb_the_proxy_cannot_forward(routes):
    offenders = [f"{method} {path}" for path, method in routes if method not in PROXYABLE]
    assert not offenders, f"unreachable through the AppAPI proxy: {offenders}"


def test_info_xml_declares_every_verb_the_api_uses(routes):
    """AppAPI 34+ matches path AND verb together, so an undeclared verb does
    not merely fail — it falls through to the next entry that does match. An
    admin route whose verb is missing from the ADMIN entry would be served by
    the USER catch-all instead: a privilege downgrade, not a 405."""
    declared = _declared_routes()
    undeclared, downgraded = [], []
    for path, method in routes:
        if method not in PROXYABLE:
            continue  # reported by the test above
        # AppAPI's PHP proxy matched the path without its leading slash up
        # to 33; 34+ and HaRP match it with one. A route must catch both.
        for proxy_path in (path.lstrip("/"), "/" + path.lstrip("/")):
            matches = [
                url
                for url, verbs in declared
                if re.search(url, proxy_path, re.IGNORECASE) and method in verbs
            ]
            if not matches:
                undeclared.append(f"{method} {proxy_path}")
            elif proxy_path.lstrip("/").startswith("api/v1/admin/") and "admin" not in matches[0]:
                downgraded.append(f"{method} {proxy_path} would be served by {matches[0]}")
    assert not undeclared, f"no <route> declares these: {undeclared}"
    assert not downgraded, f"admin routes escaping the ADMIN entry: {downgraded}"


def test_register_script_carries_the_same_routes():
    """scripts/register.sh registers the hand-run container with a JSON copy
    of the route table; it must not drift from info.xml."""
    script = (ROOT / "scripts" / "register.sh").read_text()
    json_urls = re.findall(r'\{"url":"([^"]+)"', script)
    # the shell heredoc doubles the backslashes twice: \\\\/ in the file is \/ on the wire
    json_urls = [url.replace("\\\\\\\\", "\\") for url in json_urls]
    xml_urls = [url for url, _ in _declared_routes()]
    assert json_urls == xml_urls


def test_frontend_clients_never_send_an_unproxyable_verb():
    for client in ("frontend/src/api.ts", "frontend/src/recorder/api.ts"):
        source = (ROOT / client).read_text()
        for verb in ("PATCH", "TRACE", "CONNECT"):
            assert f"'{verb}'" not in source, f"{client} sends {verb}, which the proxy drops"


def test_every_download_refuses_to_be_cached(routes):
    """AppAPI's proxy adds `Cache-Control: private, max-age=3600` to any
    non-JSON response that does not set its own
    (ExAppProxyController::buildProxyResponse). For downloads that is wrong,
    and for one it leaked data: /api/v1/public/recorder/report.pdf is the same
    URL for every assembly, so a phone used in two of them served the first
    one's report from cache for an hour.

    Checked against the source rather than a live response, so an endpoint
    added later cannot quietly reintroduce it.
    """
    import inspect

    from citizens.api import files, public_recorder, reports

    downloads = {
        "report.md": (reports, "assembly_report_markdown"),
        "report.pdf": (reports, "assembly_report_pdf"),
        "phone report.pdf": (public_recorder, "published_report_pdf"),
        "recording audio": (files, "download_audio"),
        "zip archives": (files, "_zip_response"),
    }
    missing = []
    for label, (module, name) in downloads.items():
        source = inspect.getsource(getattr(module, name))
        if "download_headers" not in source and "NO_STORE" not in source:
            missing.append(label)
    assert not missing, (
        "these downloads do not set Cache-Control, so the proxy will cache them "
        f"for an hour: {missing}"
    )


def test_the_ui_bundle_is_revalidated_not_cached_for_an_hour():
    """The organizer bundle is served from a URL that never changes, and the
    proxy stamps `private, max-age=3600` on anything that sets no
    Cache-Control. That meant every deploy could serve the PREVIOUS build for
    an hour, with the browser never asking.

    Checked at the mount, because there is no request-level place to notice it.
    """
    import inspect

    from citizens import main

    source = inspect.getsource(main.create_app)
    for directory in ("js", "css", "img"):
        assert f'"{directory}"' in source, f"{directory}/ is no longer mounted here"
    assert "_RevalidatedStatic" in source, (
        "static assets must be served with a Cache-Control, or the proxy adds "
        "its own hour and deploys stop reaching the browser"
    )
    assert "map_app_static=False" in inspect.getsource(main.lifespan), (
        "nc_py_api would otherwise mount the same directories without a "
        "Cache-Control, and its mount could win"
    )
    assert "no-cache" in inspect.getsource(main._RevalidatedStatic.file_response)
