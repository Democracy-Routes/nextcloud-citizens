#!/bin/sh
# Rebuild the documentation site into /var/www/docs.democracyroutes.com.
#   sh scripts/docs-build.sh
# Step 1 regenerates the OpenAPI document (when the citizens-test image is
# available; otherwise the existing site-docs/_generated/openapi.json is used),
# step 2 turns it into Markdown pages, step 3 builds the site with --strict.
set -eu
REPO="$(cd "$(dirname "$0")/.." && pwd)"
OUT=/var/www/docs.democracyroutes.com
mkdir -p "$REPO/site-docs/_generated" "$OUT"

if docker image inspect citizens-test >/dev/null 2>&1; then
    docker run --rm --user root -v "$REPO":/app -w /app -e PYTHONPATH=/app \
        -e APP_ID=citizens -e APP_VERSION=0.0.0-docs -e APP_SECRET=docs \
        -e NEXTCLOUD_URL=http://nextcloud.test -e APP_PERSISTENT_STORAGE=/tmp/docs-storage \
        -e CITIZENS_DEV=0 --entrypoint python citizens-test -c \
        "import json; from citizens.main import create_app; json.dump(create_app().openapi(), open('/app/site-docs/_generated/openapi.json','w'), indent=1)"
fi

python3 "$REPO/site-docs/gen_api.py"

docker run --rm -v /root/NextCloud-Citizen/site-docs:/docs -v /var/www/docs.democracyroutes.com:/out squidfunk/mkdocs-material build --strict -d /out
