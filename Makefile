UV ?= uv
PYTEST ?= $(UV) run --group dev python -m pytest
VERSION = $(shell $(UV) version --short)
DIST_DIR ?= dist
WHEEL = $(DIST_DIR)/onto_lang-$(VERSION)-py3-none-any.whl
RELEASE_FILES = $(DIST_DIR)/onto_lang-$(VERSION).tar.gz $(WHEEL)
HEXA_SRC ?= ../hexa/src/py
GIT_REMOTE ?= origin
GIT_BRANCH ?= main
SKILLS = $(notdir $(wildcard docs/skills/*))
# Where agents look for skills; each skill is linked, so edits here apply at once.
SKILLS_DIRS ?= $(HOME)/.config/opencode/skills $(HOME)/.agents/skills

.PHONY: test test-hexa test-release release install-skills uninstall-skills

test:
	$(PYTEST) -q

test-hexa:
	PYTHONPATH="$(abspath $(HEXA_SRC)):$$PYTHONPATH" $(UV) run python -c 'import hexa.shapes'
	PYTHONPATH="$(abspath $(HEXA_SRC)):$$PYTHONPATH" $(PYTEST) -q -o 'pythonpath=src/py'

test-release:
	$(UV) build --no-sources --out-dir "$(DIST_DIR)"
	@set -eu; \
		tmp=$$(mktemp -d); \
		trap 'rm -rf "$$tmp"' EXIT; \
		$(UV) venv --quiet "$$tmp/venv"; \
		$(UV) pip install --quiet --no-deps --python "$$tmp/venv/bin/python" "$(WHEEL)"; \
		cd "$$tmp"; \
		unset PYTHONPATH; \
		./venv/bin/onto --help >/dev/null; \
		./venv/bin/python -m onto --help >/dev/null; \
		printf 'IMPLEMENTATIONS = {}\n' > smoke_first.py; \
		cp smoke_first.py smoke_second.py; \
		./venv/bin/onto fn test --impl smoke_first --impl smoke_second >/dev/null

release:
	@set -eu; \
		status=$$(git status --porcelain --untracked-files=normal); \
		if [ -n "$$status" ]; then \
			echo "release requires a clean Git checkout (commit or stash changes first)" >&2; exit 1; \
		fi
	@if git rev-parse -q --verify "refs/tags/v$(VERSION)" >/dev/null; then \
		echo "tag v$(VERSION) already exists" >&2; exit 1; \
	fi
	UV_LOCKED=1 $(MAKE) test-hexa
	$(MAKE) test-release
	@set -eu; \
		commit=$$(git rev-parse HEAD); \
		$(UV) publish $(RELEASE_FILES); \
		git tag -a "v$(VERSION)" -m "Release $(VERSION)" "$$commit"; \
		git push --atomic "$(GIT_REMOTE)" "$$commit:refs/heads/$(GIT_BRANCH)" "refs/tags/v$(VERSION)"

install-skills:
	@for dir in $(SKILLS_DIRS); do \
		mkdir -p "$$dir"; \
		for skill in $(SKILLS); do \
			target="$(CURDIR)/docs/skills/$$skill"; \
			if [ -e "$$dir/$$skill" ] || [ -L "$$dir/$$skill" ]; then \
				if [ "$$(readlink "$$dir/$$skill")" != "$$target" ]; then \
					echo "skipped $$dir/$$skill: exists and was not linked by this checkout"; \
				fi; \
			else \
				ln -s "$$target" "$$dir/$$skill"; \
				echo "linked  $$dir/$$skill"; \
			fi; \
		done; \
	done

uninstall-skills:
	@for dir in $(SKILLS_DIRS); do \
		for skill in $(SKILLS); do \
			if [ "$$(readlink "$$dir/$$skill")" = "$(CURDIR)/docs/skills/$$skill" ]; then \
				rm "$$dir/$$skill"; \
				echo "removed $$dir/$$skill"; \
			fi; \
		done; \
	done
