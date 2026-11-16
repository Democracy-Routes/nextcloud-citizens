# Contributing

Citizens records people's voices, so correctness and privacy come before features. Contributions are welcome. This page gives the ground rules; the repository is
[github.com/Democracy-Routes/nextcloud-citizens](https://github.com/Democracy-Routes/nextcloud-citizens).

## Priorities

When two goals conflict, resolve them in this order:

1. **Preserve recordings.** Never risk captured audio.
2. **Privacy and security.** No verbatim speech or API key where it does not belong.
3. **Failure recovery.** A crash, a dead network or a reload must be survivable.
4. **Auditability.** Every AI claim links to the evidence behind it.
5. **Usability**, then everything else.

## Guides

* [Development environment](development-environment.md): run the app locally against a Nextcloud, or standalone.
* [Conventions and the gate](conventions.md): code conventions visible in the repository, how to run the checks, and what a pull request needs.

## Pull requests

* Add or update tests: integration tests for API behavior, Playwright specs in `tests/browser/` for anything the phone does offline.
* Write comments that say why, not what.
* Run `make lint && make test` before pushing.
* Database changes need an Alembic migration in `citizens/db/migrations/versions/`; migrations run automatically at startup.
* Never commit secrets, database files or recordings.

## Reporting security issues

Do not open a public issue. Follow `SECURITY.md` in the repository.

## License

Citizens is licensed under AGPL-3.0-or-later; see `LICENSE` in the repository. Source files carry SPDX headers
(`SPDX-License-Identifier: AGPL-3.0-or-later`). Because the license is the AGPL, anyone who runs a modified version as a network service must offer its users the source.
