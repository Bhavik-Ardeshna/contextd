"""Tests for cohort Cypher row validation."""

from contextd.platform.agent_orchestration.cohort.validation import (
    validate_cohort_member_rows,
)


def test_empty_rows_valid():
    ok, err = validate_cohort_member_rows([])
    assert ok is True
    assert err == ""


def test_rows_require_node_id():
    ok, err = validate_cohort_member_rows([{"foo": 1}])
    assert ok is False
    assert "node_id" in err


def test_node_id_case_insensitive():
    ok, err = validate_cohort_member_rows([{"NODE_ID": "public.t:1"}])
    assert ok is True
    assert err == ""
