"""Module: tests._helpers — specification fixtures and structural schema checks."""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path

from jsonschema import Draft202012Validator

from onto.observations import Observations

ROOT = Path(__file__).resolve().parent.parent


@cache
def _schemaValidator(name: str, definition: str | None = None) -> Draft202012Validator:
	"""Load the schema for `name`, optionally selecting one local `definition`."""
	schema = json.loads((ROOT / "src/json" / f"{name}.schema.json").read_text())
	Draft202012Validator.check_schema(schema)
	if definition:
		schema = {"$ref": f"#/$defs/{definition}", "$defs": schema["$defs"]}
	return Draft202012Validator(schema)


def _specExample(name: str, index: int = 0, kind: str = "text") -> str:
	"""Read example `index` of `kind` from specification `name`."""
	text = (ROOT / "docs/specs" / f"{name}.md").read_text()
	return re.findall(rf"```{re.escape(kind)}\n(.*?)```", text, re.S)[index]


def _semanticClaims(log: Observations) -> list[str]:
	"""Compare retained claims without source-document ordinals, preserving metadata and conflicts."""
	return sorted(json.dumps({key: value for key, value in claim.items() if key != "n"}, sort_keys=True) for claim in log.claims)


# EOF
