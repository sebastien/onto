"""Bundles: compiled programs, model facts and resolved views as JSON for runtimes that do not compile (spec-06 Bundles)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

pytest.importorskip("hexa.shapes")

from onto import Source, loadBinding, loadFunctions, loadMapping, loadOntology, loadReferential  # noqa: E402
from onto.ontology import ViewInput  # noqa: E402
from onto.integrations.hexa import HexaBindingOperator, HexaMappingOperator, HexaViewOperator, ViewDocument, ViewRead  # noqa: E402
from onto.integrations.hexa.bundle import BUNDLE_FORMAT, bindingProgramJson, viewBundle  # noqa: E402


def operator() -> HexaViewOperator:
	source = loadOntology([Source("source.onto", "@ontology Source\nRecord\n  Id Text {key}\n  Name Text\nSpecial < Record\n")])
	target = loadOntology([Source("target.onto", """@ontology Target
@use Source as S
Entry
  Id Text {key}
  Name Text
@view Summary(id: S/Special.Id)
  entry: Entry
  entry.Name
""")], [source])
	referential = loadReferential([target], [Source("keys.ref", "@referential Keys\n@use Target as T\nT/Entry key=Id\n")])
	mapping = loadMapping(source, target, Source("source.map", "@mapping Source -> Target referential=Keys\nRecord -> Entry\n  Id <- Id\n  Name <- Name\n"),
		referentials=[referential])
	binding = loadBinding(source, Source("source.bind", "@binding Source format=json\nSpecial <- rows[*] {id=id}\n  Id <- id\n  Name <- name\n"))
	access = SimpleNamespace(describe=lambda step, value: {}, rootHandle=lambda key, value, kind: "Entry_" + value, discover=lambda state, key: (),
		fetch=lambda step, value: ViewDocument({"rows": [{"id": value, "name": "Special record"}]}, "fixture"))
	reads = {step: ViewRead(ViewInput("id", "Source/Special", "Id"), [binding]) for step in ("Second", "First")}
	return HexaViewOperator(HexaMappingOperator(source, target, referential), mapping, reads, access)


def test_a_view_bundle_is_json_with_the_catalogue_in_its_order():
	bundle = json.loads(json.dumps(viewBundle(operator())))
	assert bundle["format"] == BUNDLE_FORMAT
	assert set(bundle) == {"format", "source", "target", "bindings", "reads", "mapping", "keyTypes", "inputTargets", "views"}
	# Member order is significant: catalogue order breaks ties between reads, as in Python.
	assert list(bundle["reads"]) == ["Second", "First"]
	assert bundle["reads"]["Second"]["bindings"] == bundle["reads"]["First"]["bindings"] == ["b1"] and list(bundle["bindings"]) == ["b1"]
	view = bundle["views"]["Summary"]
	assert view["input"] == {"name": "id", "path": "Source/Special", "attr": "Id", "key": "Source/Special.Id"}
	assert view["rootTarget"] == "Target/Entry" and view["defaults"] == {"Entry.Name": "entry.Name"}
	assert view["matches"] == {"entry.Name": [{"resolved": True, "supplier": "Second"}]}
	assert bundle["target"]["types"]["Target/Entry"]["attrs"]["Name"] == {"multi": False}


def test_a_binding_program_carries_the_functions_it_calls_and_its_function_codecs():
	ontology = loadOntology([Source("t.onto", "@ontology Isolated\nItem\n  Id Text {key}\n  Label Text\n")])
	library = loadFunctions([ontology], [Source("t.fn", "@functions IsolatedFunctions\n@fn Convert Text -> Text {inverse=Restore}\n  hello => first:hello\n"
		"@fn Restore Text -> Text\n  first:hello => hello\n")])
	binding = loadBinding(ontology, Source("t.bind", "@binding Isolated\n@use IsolatedFunctions as F\n\nItem <- items[*] {id=id}\n  Label <- F/Convert(label)\n"),
		libraries=[library])
	ops = HexaBindingOperator(ontology, libraries=[library], implementations={"IsolatedFunctions/Convert": str, "IsolatedFunctions/Restore": str})
	program = json.loads(json.dumps(bindingProgramJson(ops, ops.compile(binding))))
	codec = program["codecs"]["IsolatedFunctions.Convert"]
	assert list(program["codecs"]) == ["IsolatedFunctions.Convert"]
	assert (codec["function"], codec["inverse"], codec["canonical"]) == ("IsolatedFunctions/Convert", "IsolatedFunctions/Restore", "$Text")
	assert set(program["functions"]) == {"IsolatedFunctions/Convert", "IsolatedFunctions/Restore"}
	assert program["functions"]["IsolatedFunctions/Convert"] == {"args": [{"kind": "builtin", "builtin": "Text"}], "result": {"kind": "builtin", "builtin": "Text"}}
	assert all(scope["shape"] and scope["template"] for scope in program["scopes"])


# EOF
