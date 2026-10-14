import pytest

from example_service import is_missing, load_settings, paginate


def test_paginate_splits_evenly() -> None:
    assert paginate(["a", "b", "c", "d"], 2) == [["a", "b"], ["c", "d"]]


def test_paginate_rejects_zero_page_size() -> None:
    with pytest.raises(ValueError, match="page_size"):
        paginate(["a"], 0)


def test_settings_are_required() -> None:
    settings = load_settings({"REQUEST_TIMEOUT_SECONDS": "2.5", "PAGE_SIZE": "20"})
    assert settings.page_size == 20
    with pytest.raises(KeyError):
        load_settings({"PAGE_SIZE": "20"})


def test_not_found_is_missing() -> None:
    assert is_missing(404)
    assert not is_missing(200)
