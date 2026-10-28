# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Mail for standalone mode: invitation and password-reset links.

Two transports. `smtp` from CITIZENS_SMTP_URL; `log` when it is empty, which
writes the mail to the log with the link's token redacted — for development
and tests, never a substitute for a mail server. Sending runs as a job
(SEND_MAIL), never inside a request: a slow mail server must not hold a
request or, worse, a write transaction.

The job payload names the token row, not the token: the raw token is read
from its encrypted copy at send time (accounts.token_for_mail) and the copy
is cleared, so neither the jobs table nor the log ever holds a usable link.
"""

import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from urllib.parse import unquote, urlparse

from sqlalchemy.orm import Session

from citizens.config import get_settings
from citizens.logging_setup import get_logger
from citizens.services import accounts
from citizens.services.report_text import normalize_language

log = get_logger(__name__)

#: the link the organizer page understands (App.vue reads ?set-password=)
SET_PASSWORD_QUERY = "set-password"
_TOKEN_IN_TEXT = re.compile(r"(set-password=)[^&\s]+")


class PermanentMailError(Exception):
    """Do not retry: the token is gone or the address is unusable."""


@dataclass(frozen=True)
class Transport:
    kind: str  # "log" | "smtp"
    host: str = ""
    port: int = 0
    username: str = ""
    password: str = ""
    tls: str = "none"  # "none" | "starttls" | "tls"


def transport() -> Transport:
    url = get_settings().citizens_smtp_url.strip()
    if not url:
        return Transport(kind="log")
    parsed = urlparse(url)
    if parsed.scheme not in ("smtp", "smtps") or not parsed.hostname:
        log.error("mail_url_invalid", scheme=parsed.scheme)
        return Transport(kind="log")
    if parsed.scheme == "smtps":
        tls = "tls"
    else:
        starttls = (parsed.query or "").find("starttls=0") < 0 and parsed.port not in (25, None)
        tls = "starttls" if starttls else "none"
    return Transport(
        kind="smtp",
        host=parsed.hostname,
        port=parsed.port or (465 if tls == "tls" else 587 if tls == "starttls" else 25),
        username=unquote(parsed.username or ""),
        password=unquote(parsed.password or ""),
        tls=tls,
    )


def configured() -> bool:
    return transport().kind == "smtp"


def sender() -> str:
    settings = get_settings()
    if settings.citizens_mail_from.strip():
        return settings.citizens_mail_from.strip()
    host = urlparse(settings.citizens_public_url).hostname or "localhost"
    return f"citizens@{host}"


def redact(text: str) -> str:
    return _TOKEN_IN_TEXT.sub(r"\1[redacted]", text)


def send(to: str, subject: str, body: str) -> None:
    """Deliver one plain-text mail through the configured transport."""
    kind = transport()
    if kind.kind == "log":
        log.info("mail_logged", to=to, subject=subject, body=redact(body))
        return
    message = EmailMessage()
    message["From"] = formataddr(("Citizens", sender())) if "@" in sender() else sender()
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    if kind.tls == "tls":
        with smtplib.SMTP_SSL(kind.host, kind.port, timeout=20, context=ssl.create_default_context()) as smtp:
            if kind.username:
                smtp.login(kind.username, kind.password)
            smtp.send_message(message)
        return
    with smtplib.SMTP(kind.host, kind.port, timeout=20) as smtp:
        if kind.tls == "starttls":
            smtp.starttls(context=ssl.create_default_context())
        if kind.username:
            smtp.login(kind.username, kind.password)
        smtp.send_message(message)


# --- templates -------------------------------------------------------------

_TEXT = {
    "en": {
        "invite_subject": "Your Citizens account at {instance}",
        "invite_body": (
            "Hello {name},\n\n"
            "An account has been created for you on Citizens at {instance}.\n"
            "Choose your password with this link (valid for {hours} hours):\n\n"
            "{link}\n\n"
            "If you were not expecting this, you can ignore this message.\n"
        ),
        "reset_subject": "Reset your Citizens password",
        "reset_body": (
            "Hello {name},\n\n"
            "Someone asked to reset the password of your Citizens account at {instance}.\n"
            "Choose a new password with this link (valid for {hours} hours):\n\n"
            "{link}\n\n"
            "If it was not you, nothing changes: ignore this message.\n"
        ),
    },
    "it": {
        "invite_subject": "Il tuo account Citizens su {instance}",
        "invite_body": (
            "Ciao {name},\n\n"
            "È stato creato un account per te su Citizens, {instance}.\n"
            "Scegli la tua password con questo link (valido per {hours} ore):\n\n"
            "{link}\n\n"
            "Se non te lo aspettavi, puoi ignorare questo messaggio.\n"
        ),
        "reset_subject": "Reimposta la password di Citizens",
        "reset_body": (
            "Ciao {name},\n\n"
            "Qualcuno ha chiesto di reimpostare la password del tuo account Citizens su {instance}.\n"
            "Scegli una nuova password con questo link (valido per {hours} ore):\n\n"
            "{link}\n\n"
            "Se non sei stato tu, non cambia nulla: ignora questo messaggio.\n"
        ),
    },
    "de": {
        "invite_subject": "Dein Citizens-Konto bei {instance}",
        "invite_body": (
            "Hallo {name},\n\n"
            "Für dich wurde ein Konto bei Citizens auf {instance} angelegt.\n"
            "Wähle dein Passwort mit diesem Link (gültig für {hours} Stunden):\n\n"
            "{link}\n\n"
            "Falls du das nicht erwartet hast, kannst du diese Nachricht ignorieren.\n"
        ),
        "reset_subject": "Citizens-Passwort zurücksetzen",
        "reset_body": (
            "Hallo {name},\n\n"
            "Jemand hat darum gebeten, das Passwort deines Citizens-Kontos bei {instance} zurückzusetzen.\n"
            "Wähle ein neues Passwort mit diesem Link (gültig für {hours} Stunden):\n\n"
            "{link}\n\n"
            "Falls du es nicht warst, ändert sich nichts: ignoriere diese Nachricht.\n"
        ),
    },
    "fr": {
        "invite_subject": "Ton compte Citizens sur {instance}",
        "invite_body": (
            "Bonjour {name},\n\n"
            "Un compte a été créé pour toi sur Citizens, {instance}.\n"
            "Choisis ton mot de passe avec ce lien (valable {hours} heures) :\n\n"
            "{link}\n\n"
            "Si tu ne t'y attendais pas, tu peux ignorer ce message.\n"
        ),
        "reset_subject": "Réinitialise ton mot de passe Citizens",
        "reset_body": (
            "Bonjour {name},\n\n"
            "Quelqu'un a demandé la réinitialisation du mot de passe de ton compte Citizens sur {instance}.\n"
            "Choisis un nouveau mot de passe avec ce lien (valable {hours} heures) :\n\n"
            "{link}\n\n"
            "Si ce n'était pas toi, rien ne change : ignore ce message.\n"
        ),
    },
    "es": {
        "invite_subject": "Tu cuenta de Citizens en {instance}",
        "invite_body": (
            "Hola {name},\n\n"
            "Se ha creado una cuenta para ti en Citizens, {instance}.\n"
            "Elige tu contraseña con este enlace (válido durante {hours} horas):\n\n"
            "{link}\n\n"
            "Si no lo esperabas, puedes ignorar este mensaje.\n"
        ),
        "reset_subject": "Restablece tu contraseña de Citizens",
        "reset_body": (
            "Hola {name},\n\n"
            "Alguien ha solicitado restablecer la contraseña de tu cuenta de Citizens en {instance}.\n"
            "Elige una nueva contraseña con este enlace (válido durante {hours} horas):\n\n"
            "{link}\n\n"
            "Si no has sido tú, no cambia nada: ignora este mensaje.\n"
        ),
    },
}


def _t(language: str | None, key: str, **fmt) -> str:
    strings = _TEXT.get(normalize_language(language), _TEXT["en"])
    template = strings.get(key) or _TEXT["en"][key]
    return template.format(**fmt)


def set_password_link(raw_token: str) -> str:
    base = get_settings().citizens_public_url.rstrip("/")
    return f"{base}/?{SET_PASSWORD_QUERY}={raw_token}"


def render(kind: str, language: str | None, name: str, raw_token: str, hours: int) -> tuple[str, str]:
    instance = urlparse(get_settings().citizens_public_url).hostname or "Citizens"
    fmt = {"name": name, "instance": instance, "link": set_password_link(raw_token), "hours": hours}
    return _t(language, f"{kind}_subject", **fmt), _t(language, f"{kind}_body", **fmt)


# --- the job ---------------------------------------------------------------

def enqueue_account_mail(session: Session, token_id: str) -> None:
    from citizens.services.jobs import enqueue_job

    enqueue_job(session, "SEND_MAIL", {"token_id": token_id}, max_attempts=5)


def handle_send_mail(session: Session, payload: dict) -> None:
    """Job handler. Reads and clears the token under the job's transaction,
    commits, THEN talks to the mail server — the writer slot is never held
    across the network."""
    from citizens.jobs.handlers import PermanentJobError

    found = accounts.token_for_mail(session, payload.get("token_id", ""))
    if found is None:
        raise PermanentJobError("Account token is gone or already sent")
    token, user, raw = found
    if not user.email:
        raise PermanentJobError("The account has no email address")
    hours = round((token.expires_at - token.created_at).total_seconds() / 3600) or 1
    subject, body = render(token.kind, user.language, user.display_name or user.username, raw, hours)
    to = user.email
    session.commit()
    send(to, subject, body)
    log.info("account_mail_sent", kind=token.kind, user_id=user.id)
