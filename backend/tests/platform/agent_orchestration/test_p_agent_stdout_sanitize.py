"""Tests for P-Agent stdout sanitization before Analysis / final LLM."""

from contextd.platform.agent_orchestration.p_agent_functions import (
    sanitize_p_agent_stdout_for_llm,
)


def test_sanitize_strips_pandas_info_block() -> None:
    noisy = """=== Data info ===
<class 'pandas.core.frame.DataFrame'>
RangeIndex: 3 entries, 0 to 2
Data columns (total 2 columns):
 #   Column        Non-Null Count  Dtype
---  ------        --------------  -----
 0   status        3 non-null      object
 1   member_count  3 non-null      int64
dtypes: int64(1), object(1)
memory usage: 180.0+ bytes

The DataFrame does not contain a time component.
"""
    out = sanitize_p_agent_stdout_for_llm(noisy)
    assert "<class 'pandas.core.frame.DataFrame'>" not in out
    assert "memory usage:" not in out.lower()
    assert "time component" in out


def test_sanitize_empty_returns_empty() -> None:
    assert sanitize_p_agent_stdout_for_llm("") == ""
    assert sanitize_p_agent_stdout_for_llm("   ") == ""
