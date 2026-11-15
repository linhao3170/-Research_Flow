from __future__ import annotations

import pytest

from researchflow.contracts.encoding import canonical_text, hash_payload


def test_object_keys_are_sorted_by_utf16_code_units() -> None:
    assert canonical_text({"b": 1, "a": 2}) == '{"a":2,"b":1}'
    # U+1F600 is a surrogate pair (D83D DE00), which sorts before U+FFFF.
    assert canonical_text({"\uffff": 1, "😀": 2}) == '{"😀":2,"￿":1}'


def test_arrays_preserve_order() -> None:
    assert canonical_text([3, 1, 2]) == "[3,1,2]"


def test_numbers_follow_the_supported_ecmascript_form() -> None:
    assert canonical_text([1.0, 1e-6, 1e21, 1e-7, -0.0, 1.5]) == (
        "[1,0.000001,1e+21,1e-7,0,1.5]"
    )


def test_nan_and_infinity_are_rejected() -> None:
    with pytest.raises(ValueError):
        canonical_text(float("nan"))
    with pytest.raises(ValueError):
        canonical_text(float("inf"))


def test_non_string_object_keys_are_rejected() -> None:
    with pytest.raises(TypeError):
        canonical_text({1: "x"})


def test_hash_is_independent_of_object_key_order() -> None:
    assert hash_payload({"a": 1, "b": 2}) == hash_payload({"b": 2, "a": 1})
    assert hash_payload({"a": 1}) != hash_payload({"a": 2})