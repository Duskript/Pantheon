import pytest
from harness.loader import load_harness, invalidate_all
from harness.exceptions import HarnessCircularExtendsError, HarnessNotFoundError


@pytest.fixture(autouse=True)
def clear_cache():
    invalidate_all()
    yield
    invalidate_all()


def test_base_harness_loads():
    h = load_harness("zeus-base.yaml")
    assert h["name"] == "Zeus"
    assert h["driver"] == "llm"
    assert "identity" in h


def test_studio_harness_extends():
    h = load_harness("apollo-lyric-writing.yaml")
    assert h["name"] == "Apollo"
    assert h["studio"] == "Lyric Writing"
    assert len(h.get("routing", [])) > 0
    hard_stops = h["guardrails"]["hard_stops"]
    assert len(hard_stops) > 0


def test_hard_stops_are_additive():
    base = load_harness("apollo-base.yaml")
    studio = load_harness("apollo-lyric-writing.yaml")
    base_count = len(base["guardrails"]["hard_stops"])
    studio_count = len(studio["guardrails"]["hard_stops"])
    assert studio_count >= base_count


def test_missing_harness_raises():
    with pytest.raises(HarnessNotFoundError):
        load_harness("does-not-exist.yaml")


def test_script_driver_no_model():
    h = load_harness("hestia-base.yaml")
    assert h["driver"] == "script"
    assert "model" not in h


if __name__ == "__main__":
    test_base_harness_loads()
    test_studio_harness_extends()
    test_hard_stops_are_additive()
    test_missing_harness_raises()
    test_script_driver_no_model()
