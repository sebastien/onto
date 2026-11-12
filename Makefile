UV ?= uv
PYTEST ?= $(UV) run --group dev python -m pytest
VERSION = $(shell $(UV) version --short)
RELEASE_FILES = dist/onto_lang-$(VERSION).tar.gz dist/onto_lang-$(VERSION)-py3-none-any.whl

.PHONY: test test-release release

test:
	$(PYTEST) -q

test-release:
	$(UV) build --no-sources

release: test
	$(MAKE) test-release
	$(UV) publish $(RELEASE_FILES)
