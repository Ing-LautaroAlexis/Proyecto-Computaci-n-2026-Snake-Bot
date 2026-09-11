"""Expose the existing script checks to pytest without changing their scenarios."""
import pytest
import test_refactor_equivalence as equivalence
import v3_arena_smoke as smoke


def test_existing_equivalence():
    equivalence.run_equivalence()


@pytest.mark.parametrize("index,size", enumerate(
    [(12, 20), (20, 12), (12, 12), (20, 20), (17, 14)], 1
))
def test_existing_arena_smoke(index, size):
    smoke.run_smoke_case(8800 + index, size)
