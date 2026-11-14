# Citizens documentation site

Source of https://docs.democracyroutes.com, built with MkDocs and the Material
theme.

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
