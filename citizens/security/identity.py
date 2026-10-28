# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Current-user identity.

Nextcloud mode: the AppAPI proxy authenticated the request and put the
Nextcloud user id in its headers; nc_py_api reads them. Standalone mode: the
signed session cookie names an account in app_users (security/sessions.py,
security/standalone_auth.py). Either way the rest of the app sees one
string — the owner id stored in Assembly.created_by.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request

from citizens.config import get_settings


def get_current_user_id(request: Request) -> str:
    if get_settings().is_standalone():
        from citizens.security import standalone_auth

        return standalone_auth.current_user_id(request)
    from nc_py_api.ex_app import nc_app

    user = nc_app(request).user
    if not user:
        raise HTTPException(status_code=401, detail="No authenticated Nextcloud user")
    return user


CurrentUser = Annotated[str, Depends(get_current_user_id)]
