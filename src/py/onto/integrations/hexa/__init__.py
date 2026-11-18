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

# NOTE: Imported after the check above, so a missing hexa raises `IntegrationUnavailable` first.
from .compiler import CompileError  # noqa: E402
from .model import (  # noqa: E402
	BindingProgram, BindingReport, MappingProgram, MappingReport, Outcome, ReportGap, StageNamespace, WriteReport,
)
from .operations import (  # noqa: E402
	HexaBindingOperator, HexaMappingOperator, bindingApprove, bindingCompile, bindingFormatsUpdate, bindingResult, mappingApprove,
	mappingCompile, mappingResult, programEncoding,
)
from .vocabulary import BindingCodes, MappingCodes, vocabularyConformance  # noqa: E402
from .writing import BindingWriteProgram  # noqa: E402
from .views import HexaViewOperator, ViewDocument, ViewRead, ViewReadError  # noqa: E402

__all__ = [
	"IntegrationUnavailable", "CompileError", "BindingCodes", "MappingCodes", "vocabularyConformance",
	"HexaViewOperator", "ViewDocument", "ViewRead", "ViewReadError",
	"HexaBindingOperator", "HexaMappingOperator", "bindingCompile", "bindingResult", "bindingFormatsUpdate", "bindingApprove",
	"mappingCompile", "mappingResult", "mappingApprove", "programEncoding",
	"BindingProgram", "BindingWriteProgram", "MappingProgram", "BindingReport", "MappingReport", "WriteReport", "ReportGap", "Outcome", "StageNamespace",
]

# EOF
