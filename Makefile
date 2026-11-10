PYTEST ?= uv run --no-project --with pytest python -m pytest

.PHONY: test

test:
	$(PYTEST) -q
