UV ?= uv
PYTEST ?= $(UV) run --group dev python -m pytest
VERSION = $(shell $(UV) version --short)
RELEASE_FILES = dist/onto_lang-$(VERSION).tar.gz dist/onto_lang-$(VERSION)-py3-none-any.whl
SKILLS = $(notdir $(wildcard docs/skills/*))
# Where agents look for skills; each skill is linked, so edits here apply at once.
SKILLS_DIRS ?= $(HOME)/.config/opencode/skills $(HOME)/.agents/skills

.PHONY: test test-release release install-skills uninstall-skills

test:
	$(PYTEST) -q

test-release:
	$(UV) build --no-sources

release: test
	$(MAKE) test-release
	$(UV) publish $(RELEASE_FILES)

install-skills:
	@for dir in $(SKILLS_DIRS); do \
		mkdir -p "$$dir"; \
		for skill in $(SKILLS); do \
			if [ -e "$$dir/$$skill" ] && [ ! -L "$$dir/$$skill" ]; then \
				echo "skipped $$dir/$$skill: exists and is not a link"; \
			else \
				ln -sfn "$(CURDIR)/docs/skills/$$skill" "$$dir/$$skill"; \
				echo "linked  $$dir/$$skill"; \
			fi; \
		done; \
	done

uninstall-skills:
	@for dir in $(SKILLS_DIRS); do \
		for skill in $(SKILLS); do \
			if [ -L "$$dir/$$skill" ]; then \
				rm "$$dir/$$skill"; \
				echo "removed $$dir/$$skill"; \
			fi; \
		done; \
	done
