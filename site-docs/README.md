# Democracy Routes documentation site

Source of https://docs.democracyroutes.com, built with MkDocs and the Material
theme. It documents the whole platform: Citizens (the original sections), Polis
(`docs/polis/`) and the bridge between them (`docs/bridge/`).

* `mkdocs.yml` is the configuration and the navigation.
* `docs/` holds the pages. Edit them in place.
* `gen_api.py` turns `_generated/openapi.json` into `docs/reference/api/`.

## Build

```sh
sh scripts/docs-build.sh
```

This regenerates the OpenAPI document (needs the `citizens-test` Docker image),
rewrites the API reference pages, and builds the site with `--strict` into
`/var/www/docs.democracyroutes.com` using the `squidfunk/mkdocs-material`
image. A broken link or a page missing from the navigation fails the build.

## Generated, not hand-written

* `site-docs/_generated/` (the OpenAPI document)
* `site-docs/docs/reference/api/` (one page per route group)

`docs/reference/changelog.md` is a copy of the 0.7 and later sections of
`CHANGELOG.md`; refresh it by hand when the changelog changes.

The pages describe only what the repository's own documents and code say. When
`docs/*.md` in the repository changes, update the matching page here.

## The Polis and bridge sections

`docs/polis/` (tab "Polis") and `docs/bridge/` (tab "Citizens + Polis") are
written by hand from the Citizens-Polis repository, checked out at
`/root/Citizens-Polis` and published at
[github.com/Democracy-Routes/polisorbis](https://github.com/Democracy-Routes/polisorbis):
its `README.md`, `CHANGELOG.md`, `docs/`, `deploy/`, `example.env` and the route
code under `server/src/`. That repository is read-only for this site. When it
changes, refresh the pages by hand:

* `docs/polis/changelog.md` is a static copy of the fork part of its `CHANGELOG.md`.
* `docs/polis/api.md`, `docs/bridge/contract.md` and `docs/polis/configuration.md`
  follow the route code and `example.env`.
* `docs/assets/polis/docker-architecture.png` is copied from its `docs/`.
* `docs/reference/polis-contract.md` only points to `docs/bridge/contract.md`.
