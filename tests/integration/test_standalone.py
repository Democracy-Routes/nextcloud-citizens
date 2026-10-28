# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Standalone mode end to end: sign-in, ownership, the admin guard, Settings
in the SQLite store, accounts and their mails — and the one invariant that
matters most: a route without a sign-in is a route with a sign-in required.
"""

import json

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from citizens.config import get_settings
from citizens.db.models.accounts import AccountToken, AppUser
from citizens.db.session import get_engine, session_scope
from citizens.main import create_app
from citizens.security.identity import get_current_user_id
from citizens.security.sessions import CLIENT_HEADER, CLIENT_HEADER_VALUE, COOKIE_NAME
from citizens.services import accounts, mail, provider_config, public_url

CLIENT = {CLIENT_HEADER: CLIENT_HEADER_VALUE}


@pytest.fixture
def standalone_env(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ID", "citizens")
    monkeypatch.setenv("APP_VERSION", "0.0.0-test")
    monkeypatch.setenv("APP_SECRET", "test-secret")
    monkeypatch.setenv("NEXTCLOUD_URL", "")
    monkeypatch.setenv("CITIZENS_MODE", "standalone")
    monkeypatch.setenv("CITIZENS_PUBLIC_URL", "https://citizens.test")
    monkeypatch.setenv("CITIZENS_SMTP_URL", "")
    monkeypatch.setenv("CITIZENS_BOOTSTRAP_ADMIN_USER", "boot")
    monkeypatch.setenv("CITIZENS_BOOTSTRAP_ADMIN_PASSWORD", "bootstrap-password")
    monkeypatch.setenv("APP_PERSISTENT_STORAGE", str(tmp_path / "storage"))
    monkeypatch.setenv("CITIZENS_DEV", "0")
    get_settings.cache_clear()
    provider_config.reset_default_store()
    provider_config.invalidate_snapshot()
    public_url.reset()
    yield get_settings()
    get_settings.cache_clear()
    provider_config.reset_default_store()
    provider_config.invalidate_snapshot()
    public_url.reset()


@pytest.fixture
def app(standalone_env):
    # with_auth=True: standalone adds no AppAPI middleware, every route
    # authenticates itself — exactly what this file checks
    # https: the session cookie is Secure when the public URL is, and the
    # client only sends Secure cookies over https
    with TestClient(create_app(with_auth=True), base_url="https://testserver") as client:
        yield client


def _create(username: str, role: str, password: str = "a-good-password", email: str | None = None) -> str:
    with session_scope() as session:
        user = accounts.create_user(
            session, username=username, role=role, password=password, email=email
        )
        return user.id


def _status(client: TestClient, method: str, path: str, **kwargs) -> int:
    return getattr(client, method)(path, headers=CLIENT, **kwargs).status_code


def _login(client: TestClient, username: str, password: str = "a-good-password") -> TestClient:
    response = client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}, headers=CLIENT
    )
    assert response.status_code == 200, response.text
    assert COOKIE_NAME in response.cookies
    return client


def test_config_and_unauthenticated_requests(app):
    config = app.get("/api/v1/auth/config").json()
    assert config["mode"] == "standalone"
    assert config["login"] == {"password": True, "oidc": False}
    assert config["mail"] is False
    assert app.get("/api/v1/assemblies").status_code == 401
    assert app.get("/api/v1/auth/me").status_code == 401
    assert app.get("/api/v1/admin/providers").status_code == 401
    assert app.get("/heartbeat").json() == {"status": "ok"}
    page = app.get("/", headers={"Accept-Language": "it-IT,it;q=0.9,en;q=0.8"})
    assert page.status_code == 200
    assert '<html lang="it">' in page.text
    assert "citizens-main.bundle.js?v=0.0.0-test" in page.text
    assert page.headers["cache-control"] == "no-store"
    assert "script-src 'self'" in page.headers["content-security-policy"]


def test_bootstrap_admin_exists_once(app):
    with session_scope() as session:
        users = session.scalars(select(AppUser)).all()
    assert [(u.username, u.role) for u in users] == [("boot", "admin")]
    _login(app, "boot", "bootstrap-password")
    me = app.get("/api/v1/auth/me").json()
    assert (me["username"], me["role"], me["mode"]) == ("boot", "admin", "standalone")


def test_login_refusals(app):
    _create("anna", "organizer")
    login = "/api/v1/auth/login"
    assert _status(app, "post", login, json={"username": "anna", "password": "wrong-one"}) == 401
    assert _status(app, "post", login, json={"username": "nobody", "password": "a-good-password"}) == 401
    with session_scope() as session:
        user = session.scalar(select(AppUser).where(AppUser.username == "anna"))
        user.disabled = True
    assert _status(app, "post", login, json={"username": "anna", "password": "a-good-password"}) == 401


def test_ownership_and_client_header(app):
    _create("anna", "organizer")
    _create("bruno", "organizer")
    _login(app, "anna")
    body = {
        "name": "Anna's assembly", "description": "", "language": "it",
        "recording_mode": "orchestrated", "expected_participants": 10,
        "default_table_count": 2, "analysis_instructions": "", "rounds": [],
    }
    # an unsafe request without the client header is how a cross-site form arrives
    assert app.post("/api/v1/assemblies", json=body).status_code == 403
    created = app.post("/api/v1/assemblies", json=body, headers=CLIENT)
    assert created.status_code == 201, created.text
    assembly_id = created.json()["id"]
    assert app.get("/api/v1/assemblies").json()[0]["id"] == assembly_id

    other = TestClient(app.app, base_url="https://testserver")
    _login(other, "bruno")
    assert other.get("/api/v1/assemblies").json() == []
    assert other.get(f"/api/v1/assemblies/{assembly_id}").status_code == 404

    # sign-out, and the cookie is gone
    assert app.post("/api/v1/auth/logout", headers=CLIENT).status_code == 204
    assert app.get("/api/v1/auth/me").status_code == 401


def test_admin_guard_is_the_role(app):
    _create("anna", "organizer")
    _create("root", "admin")
    _login(app, "anna")
    assert app.get("/api/v1/admin/providers").status_code == 403
    assert app.get("/api/v1/admin/users").status_code == 403
    admin = TestClient(app.app, base_url="https://testserver")
    _login(admin, "root")
    assert admin.get("/api/v1/admin/providers").status_code == 200
    assert admin.get("/api/v1/admin/users").json()["users"][0]["username"] == "anna"


def test_settings_live_in_sqlite_and_secrets_are_encrypted(app):
    _create("root", "admin")
    _login(app, "root")
    saved = app.put(
        "/api/v1/admin/providers",
        json={
            "organization_name": "Comune di Prova",
            "mistral_api_key": "sk-secret-value",
            "stt_provider": "mistral",
        },
        headers=CLIENT,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["organization_name"] == "Comune di Prova"
    with get_engine().connect() as conn:
        rows = dict(conn.execute(text("SELECT key, value FROM app_config")).all())
    assert rows["organization_name"] == "Comune di Prova"
    assert rows["mistral_api_key"] != "sk-secret-value"
    assert "sk-secret-value" not in json.dumps(rows)
    # the store decrypts, and the snapshot the phones read saw the save
    assert provider_config.default_store().get_value("mistral_api_key") == "sk-secret-value"
    assert provider_config.config_snapshot().organization_name == "Comune di Prova"
    # the recorder link is the public URL, not a proxy path
    assert public_url.recorder_page_url() == "https://citizens.test/recorder.html"


def test_accounts_invitation_reset_and_last_admin(app, caplog):
    _create("root", "admin")
    _login(app, "root")
    created = app.post(
        "/api/v1/admin/users",
        json={
            "username": "Carla", "display_name": "Carla", "email": "Carla@Example.org",
            "role": "organizer", "language": "it",
        },
        headers=CLIENT,
    )
    assert created.status_code == 201, created.text
    assert created.json()["invited"] is True
    assert created.json()["has_password"] is False
    carla_id = created.json()["id"]

    # the mail job carries the token id only; sending logs a redacted link
    from citizens.jobs.handlers import HANDLERS

    with session_scope() as session:
        token = session.scalar(select(AccountToken).where(AccountToken.user_id == carla_id))
        assert token.kind == "invite" and token.token_encrypted
        token_id = token.id
    with session_scope() as session:
        with caplog.at_level("INFO"):
            HANDLERS["SEND_MAIL"](session, {"token_id": token_id})
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "set-password=[redacted]" in logged
    assert "carla@example.org" in logged
    with session_scope() as session:
        token = session.get(AccountToken, token_id)
        assert token.token_encrypted is None  # the link left the database with the mail

    # Carla follows the link (the test takes the raw token the way the
    # mail did: before it was cleared — so re-issue one and read it)
    with session_scope() as session:
        user = session.get(AppUser, carla_id)
        fresh = accounts.issue_token(session, user, "invite")
        raw = accounts.token_for_mail(session, fresh.id)[2]
    landing = TestClient(app.app, base_url="https://testserver")
    set_password = "/api/v1/auth/set-password"
    assert _status(landing, "post", set_password, json={"token": raw, "password": "short"}) == 422
    with session_scope() as session:
        user = session.get(AppUser, carla_id)
        fresh = accounts.issue_token(session, user, "invite")
        raw = accounts.token_for_mail(session, fresh.id)[2]
    done = landing.post(set_password, json={"token": raw, "password": "carla-password-1"}, headers=CLIENT)
    assert done.status_code == 200, done.text
    assert done.json()["email_verified"] is True
    assert landing.get("/api/v1/auth/me").json()["username"] == "carla"
    # a spent link is refused
    assert _status(landing, "post", set_password, json={"token": raw, "password": "carla-password-2"}) == 404

    # reset never says whether the address exists
    assert _status(app, "post", "/api/v1/auth/reset", json={"email": "nobody@example.org"}) == 202
    assert _status(app, "post", "/api/v1/auth/reset", json={"email": "carla@example.org"}) == 202

    # the last administrator stays one
    with session_scope() as session:
        root_id = session.scalar(select(AppUser).where(AppUser.username == "root")).id
        boot_id = session.scalar(select(AppUser).where(AppUser.username == "boot")).id
    root_url, carla_url = f"/api/v1/admin/users/{root_id}", f"/api/v1/admin/users/{carla_id}"
    # two administrators (root and the bootstrap one): demoting one is fine
    assert _status(app, "put", f"/api/v1/admin/users/{boot_id}", json={"role": "organizer"}) == 200
    assert _status(app, "put", root_url, json={"role": "organizer"}) == 409
    assert _status(app, "delete", root_url) == 409
    assert _status(app, "put", carla_url, json={"role": "admin"}) == 200
    assert _status(app, "put", root_url, json={"role": "organizer"}) == 200
    assert _status(app, "delete", carla_url) == 403  # root is no admin now


def test_every_organizer_route_requires_a_sign_in(app):
    """The invariant standalone mode rests on: in Nextcloud mode the proxy
    and the middleware guard every route; here each route must declare its
    own user. A route that forgets is open to the internet."""
    from fastapi.routing import APIRoute

    from citizens.api.admin import require_admin

    def depends_on_user(dependant) -> bool:
        if dependant.call in (get_current_user_id, require_admin):
            return True
        return any(depends_on_user(sub) for sub in dependant.dependencies)

    public_prefixes = ("/api/v1/public/", "/recorder", "/js/", "/css/", "/img/", "/l10n/")
    exempt = {"/api/v1/health", "/api/v1/auth/config", "/api/v1/auth/login", "/api/v1/auth/logout",
              "/api/v1/auth/reset", "/api/v1/auth/set-password", "/heartbeat", "/", "/index.html"}
    unguarded = []
    for route in app.app.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.path in exempt or route.path.startswith(public_prefixes):
            continue
        if not depends_on_user(route.dependant):
            unguarded.append(f"{sorted(route.methods)} {route.path}")
    assert unguarded == []


def test_nextcloud_mode_is_untouched(settings_env):
    """The existing fixture: no mode set, the AppAPI dependency stays the
    identity, the password routes do not exist."""
    assert not settings_env.is_standalone()
    application = create_app(with_auth=False)

    def fake_user(request: Request) -> str:
        return "tester"

    application.dependency_overrides[get_current_user_id] = fake_user
    with TestClient(application) as client:
        assert client.get("/api/v1/auth/config").json()["mode"] == "nextcloud"
        assert client.get("/api/v1/auth/me").json() == {"id": "tester", "mode": "nextcloud"}
        assert client.post("/api/v1/auth/login", json={"username": "a", "password": "b"}).status_code == 404
        assert client.get("/api/v1/admin/users").status_code == 404
        assert client.get("/").status_code == 404
    assert not mail.configured()
