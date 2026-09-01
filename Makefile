.DEFAULT_GOAL := help

.PHONY: help
help:
	@echo "Nextcloud Citizens — development targets"
	@echo ""
	@echo "  make up          build dev image and (re)start the dev container (auto-reload)"
	@echo "  make register    register the manual-install daemon + Citizens ExApp in AppAPI"
	@echo "  make unregister  remove the Citizens ExApp registration"
	@echo "  make logs        tail the dev container logs (pretty structlog output)"
	@echo "  make test        run the Python and frontend test suites"
	@echo "  make test-py     run only the Python test suite"
	@echo "  make test-frontend  run only the frontend (vitest) suite"
	@echo "  make lint        run ruff"
	@echo "  make dev-reset   wipe ONLY Citizens app data (asks for confirmation)"
	@echo ""
	@echo "  make version VERSION=x.y.z   set the version everywhere it is declared"
	@echo "  make appstore                package the App Store metadata archive"
	@echo "  make appstore-check          validate info.xml the way the store does"

.PHONY: up
up:
	sh scripts/dev-up.sh

.PHONY: register
register:
	sh scripts/register.sh

.PHONY: unregister
unregister:
	sh scripts/unregister.sh

.PHONY: logs
logs:
	docker logs -f --tail 200 nc_app_citizens

# Tests run inside the app container image: the runtime is Python 3.12 there,
# and this host is too memory-constrained for a native venv. WITH_TEST_TOOLS
# adds espeak-ng (synthetic speech for transcription tests); the published
# image never carries it.
.PHONY: test
test: test-py test-frontend

.PHONY: test-py
test-py:
	docker build -q --build-arg WITH_TEST_TOOLS=1 -t citizens-test . >/dev/null
	docker run --rm --user root -v "$(CURDIR)":/app -w /app --entrypoint sh citizens-test \
		-c "pip install -q pytest ruff && python -m pytest -q"

# Component and unit tests for both Vue bundles (organizer SPA + phone
# recorder). Runs in node:22 so the host's node version is irrelevant; specs
# live in tests/frontend/ with the rest of the suite.
.PHONY: test-frontend
test-frontend:
	docker run --rm --user root -v "$(CURDIR)":/app -w /app/frontend node:22-alpine \
		sh -c "npm ci --no-audit --no-fund && npm test"

.PHONY: lint
lint:
	docker build -q --build-arg WITH_TEST_TOOLS=1 -t citizens-test . >/dev/null
	docker run --rm --user root -v "$(CURDIR)":/app -w /app --entrypoint sh citizens-test \
		-c "pip install -q ruff && python -m ruff check citizens tests"

.PHONY: dev-reset
dev-reset:
	sh scripts/dev-reset.sh

.PHONY: version
version:
	sh scripts/set-version.sh "$(VERSION)"

# The App Store archive carries metadata only — the code ships as the Docker
# image referenced by <docker-install>. Constraints enforced by the store:
# exactly one top-level folder named after the app id, <= 20 MB, no symlinks.
.PHONY: appstore
appstore:
	rm -rf build/citizens build/citizens.tar.gz
	mkdir -p build/citizens/appinfo build/citizens/img
	cp appinfo/info.xml build/citizens/appinfo/
	cp CHANGELOG.md LICENSE README.md build/citizens/
	cp img/app.svg build/citizens/img/
	tar --format=ustar -czf build/citizens.tar.gz -C build citizens
	@echo "packaged build/citizens.tar.gz ($$(du -h build/citizens.tar.gz | cut -f1))"

.PHONY: appstore-check
appstore-check:
	docker run --rm -v "$(CURDIR)":/w -w /w python:3.12-slim \
		sh -c "pip install -q lxml requests && python scripts/validate_info_xml.py"
