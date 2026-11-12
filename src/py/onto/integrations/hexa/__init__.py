"""Module: integrations.hexa — run onto bindings and mappings as hexa shape pipelines (spec-06).

Importing this package imports `hexa`; without it, the import raises
`IntegrationUnavailable`. Nothing else in onto imports hexa.
"""

from __future__ import annotations

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


class IntegrationUnavailable(ImportError):
	"""The optional library an integration needs is not installed."""


try:
	import hexa.shapes  # noqa: F401
except ImportError as error:
	raise IntegrationUnavailable("onto.integrations.hexa needs the 'hexa' package", name="hexa") from error

from .vocabulary import BindingCodes, MappingCodes, vocabularyConformance  # noqa: E402

__all__ = ["IntegrationUnavailable", "BindingCodes", "MappingCodes", "vocabularyConformance"]

# EOF
