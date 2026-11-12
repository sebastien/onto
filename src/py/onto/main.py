"""Module: main — entry point for the `onto` command line."""

from __future__ import annotations

import sys

from .cli import main

__all__ = ["main"]

if __name__ == "__main__":
	sys.exit(main())

# EOF
