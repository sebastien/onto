"""Module: formats — spec-04 formats files: parsing, printing and learning from runs."""

from __future__ import annotations

from .model import HEADER, FormatChange, Formats, FormatsEntry
from .parser import isFormat, parseFormats
from .formatter import printFormats
from .operations import formatsUpdate

__all__ = ["HEADER", "FormatChange", "Formats", "FormatsEntry", "isFormat", "parseFormats", "printFormats", "formatsUpdate"]

# EOF
