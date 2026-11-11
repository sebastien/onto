PYTEST ?= uv run --group dev python -m pytest

.PHONY: test

test:
	$(PYTEST) -q
