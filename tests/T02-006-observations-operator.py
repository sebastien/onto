"""Module: observations operator tests — ontology/mode context and feature boundaries."""

from __future__ import annotations

from copy import deepcopy

import pytest

from onto import FormatError, ObservationsOperator, Source, loadObservations, loadOntology, observationsToJson
from onto.observations import Observations, Operator
from onto.observations.formatter import printObservationsLog
from onto.observations.model import Observations as ObservationsModel
from onto.observations.operations import Operator as ObservationsOperations
from onto.observations.parser import parseObservations


ONTOLOGY = loadOntology([Source("t", "@ontology A\nPerson\n  Name Text\n")])


def testFeatureModulesKeepPublicTypesAndImportsIdentical() -> None:
	assert Observations is ObservationsModel
	assert Operator is ObservationsOperator is ObservationsOperations


def testOperatorDelegatesToTheExistingFunctionalApi() -> None:
	operator = Operator(ONTOLOGY)
	source = Source("t", "@obs A\np:Person\np.Name Old\np.Name New\n")
	log = operator.load(source)
	assert log == loadObservations(ONTOLOGY, source)
	assert operator.resolve(parseObservations(source)) == log
	assert operator.printLog(log) == operator.format(source, "log") == printObservationsLog(ONTOLOGY, log)
	before = deepcopy(log)
	state = operator.reconcile(log)
	assert operator.printState(state) == operator.format(source)
	assert operator.toJson(log) == observationsToJson(log)
	assert operator.fromJson(operator.toJson(log)) == log
	assert log == before


def testOperatorKeepsModesAndDocumentsSeparate() -> None:
	strict = Operator(ONTOLOGY)
	lenient = Operator(ONTOLOGY, "lenient")
	source = Source("t", "@obs A\np:Person\np.Missing X\n")
	with pytest.raises(FormatError):
		strict.load(source)
	log = lenient.load(source)
	assert len(log.gaps) == 1
	assert lenient.fromJson(lenient.toJson(log)).gaps == log.gaps
	assert lenient.reconcile(log).gaps == log.gaps
	with pytest.raises(FormatError):
		strict.fromJson(lenient.toJson(log))
	assert strict.mode == "strict" and lenient.mode == "lenient"
	assert lenient.load(Source("other", "@obs A\nq:Person\n")).gaps == []
	with pytest.raises(ValueError):
		Operator(ONTOLOGY, "guess")


# EOF
