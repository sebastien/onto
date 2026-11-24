"""Module: hexa split codec round-trip tests."""

import pytest

pytest.importorskip("hexa")

from hexa.shapes import Gap
from onto.integrations.hexa import vocabulary as V


def test_split_codec_parses_and_formats_roundtrip():
	assert V.splitParse(",", "b,a,,b") == {"set": ["a", "b"]}
	for members, separator in [([], ","), (["b", "a"], ","), (["a", "b"], "ab")]:
		result = V.splitFormat(separator, {"set": members})
		assert V.splitParse(separator, result) == {"set": sorted(members)}


def test_split_codec_rejects_empty_separator():
	with pytest.raises(Gap) as failure:
		V.splitParse("", "a")
	assert failure.value.code == V.SplitText.Invalid
	with pytest.raises(Gap) as failure:
		V.splitFormat("", {"set": []})
	assert failure.value.code == V.SplitText.Unformattable


@pytest.mark.parametrize("members,separator", [
	([""], ","), (["a,b"], ","), (["ab", "z"], "aba"),
])
def test_split_codec_rejects_unformattable_sets(members, separator):
	with pytest.raises(Gap) as failure:
		V.splitFormat(separator, {"set": members})
	assert failure.value.code == V.SplitText.Unformattable


# EOF
