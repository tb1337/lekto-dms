from collections.abc import Callable
from datetime import date
from uuid import UUID

import pytest

from papiq.core.domain.codes import Code
from papiq.core.domain.errors import ValidationError
from papiq.core.domain.json_value import (
    JsonObject,
    JsonValue,
    as_bool,
    as_date,
    as_int,
    as_list,
    as_number,
    as_object,
    as_text,
    as_texts,
    as_uuid,
    require_date,
    require_object,
    require_uuid,
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


ID = "0192a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"


def test_dates_ids_and_objects() -> None:
    assert (as_date("2026-03-31"), as_date("31.03.2026"), as_date(20260331)) == (
        date(2026, 3, 31),
        None,
        None,
    )
    assert (as_uuid(ID), as_uuid("nope"), as_uuid(1)) == (UUID(ID), None, None)
    assert (as_object({"a": 1}), as_object([1])) == ({"a": 1}, None)


@pytest.mark.parametrize(
    ("read", "value", "message"),
    [
        (require_date, "2026-02-30", r"^document_date: '2026-02-30' is no date \(YYYY-MM-DD\)$"),
        (require_uuid, 42, r"^document_date: 42 is no id$"),
        (require_object, [], r"^document_date: expected an object$"),
    ],
)
def test_input_that_must_fit_names_its_place(
    read: Callable[[JsonValue, str], object], value: JsonValue, message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        read(value, "document_date")
