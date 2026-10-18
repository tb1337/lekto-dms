import pytest

from papiq.core.domain.codes import Code
from papiq.core.domain.errors import ValidationError
from papiq.core.domain.json_value import (
    JsonObject,
    as_bool,
    as_int,
    as_list,
    as_number,
    as_text,
    as_texts,
)
from papiq.core.domain.reading import readings_from_json


def test_values_of_the_expected_type() -> None:
    assert (as_text("a"), as_text(1)) == ("a", None)
    assert (as_int(3), as_int(3.0), as_int(True)) == (3, None, None)
    assert (as_number(3), as_number(2.5), as_number(False)) == (3.0, 2.5, None)
    assert (as_bool(True), as_bool(1)) == (True, None)
    assert (as_list([1]), as_list({"a": 1})) == ([1], [])
    assert as_texts(["a", 1, "b"]) == ("a", "b")
    assert as_texts("ab") == ()


def test_a_truth_value_is_no_page() -> None:
    assert readings_from_json([{"page": True, "words": 3, "unsure": 0}]) == ()
    box: JsonObject = {"x": 0, "y": 0, "width": 0.5, "height": 0.5}
    code: JsonObject = {"page": 1, "format": "QR_CODE", "text": "x", "box": box}
    assert Code.from_json(code).page == 1
    with pytest.raises(ValidationError):
        Code.from_json({**code, "page": True})
