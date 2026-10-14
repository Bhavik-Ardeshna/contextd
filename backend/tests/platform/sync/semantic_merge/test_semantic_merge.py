"""Semantic merge unit tests: fake data only (no DB, env, or network)."""

from __future__ import annotations

import pytest

from contextd.core.semantic_merge_gating import (
    is_semantic_merge_allowed_for_connector,
    structured_connector_set,
)
from contextd.platform.sync.semantic_merge.alias_keys import (
    email_alias_key,
    extraction_text_for_embedding,
    name_alias_key,
)
from contextd.platform.sync.semantic_merge.property_synthesis import (
    embedding_text_hash,
    merge_dicts_deterministic,
    synthesize_summary_if_needed,
)
from contextd.platform.sync.semantic_merge.vector_similarity import cosine_similarity

# --- Fake fixtures (invented companies / people) ---

FAKE_EMAIL_MIXED = "User@FAKE-CORP.example.COM"
FAKE_PERSON_NAME = "  Taylor Morgan  "
FAKE_COMPANY = "Northwind Traders"
FAKE_BLURB_SHORT = "Regional wholesaler."
FAKE_BLURB_LONG = "Regional wholesaler of specialty foods since 1998; HQ in Portland."
FAKE_ENTITY_TYPE = "Organization"


class TestAliasKeys:
    def test_email_normalizes_to_lower(self) -> None:
        key = email_alias_key(FAKE_EMAIL_MIXED)
        assert key == "email:user@fake-corp.example.com"

    def test_email_empty_is_none(self) -> None:
        assert email_alias_key("") is None
        assert email_alias_key(None) is None

    def test_name_key_prefix_and_stability(self) -> None:
        key = name_alias_key(FAKE_PERSON_NAME)
        assert key is not None
        assert key.startswith("name:")
        assert key == name_alias_key("Taylor Morgan")

    def test_name_empty_is_none(self) -> None:
        assert name_alias_key("") is None
        assert name_alias_key(None) is None


class TestExtractionTextForEmbedding:
    def test_joins_parts_and_trims_whitespace(self) -> None:
        text = extraction_text_for_embedding(
            name=FAKE_COMPANY,
            description=FAKE_BLURB_SHORT,
            entity_type=FAKE_ENTITY_TYPE,
        )
        assert FAKE_COMPANY in text
        assert FAKE_BLURB_SHORT in text
        assert FAKE_ENTITY_TYPE in text
        assert "\n" not in text

    def test_optional_fields_omitted(self) -> None:
        text = extraction_text_for_embedding(name="Solo")
        assert text == "Solo"


class TestMergeDictsDeterministic:
    def test_merges_disjoint_keys(self) -> None:
        merged, conflict = merge_dicts_deterministic({"a": 1}, {"b": 2})
        assert not conflict
        assert merged == {"a": 1, "b": 2}

    def test_incoming_fills_none(self) -> None:
        merged, conflict = merge_dicts_deterministic({"x": None}, {"x": "filled"})
        assert not conflict
        assert merged["x"] == "filled"

    def test_nested_merge(self) -> None:
        merged, conflict = merge_dicts_deterministic(
            {"outer": {"k1": 1}},
            {"outer": {"k2": 2}},
        )
        assert not conflict
        assert merged["outer"] == {"k1": 1, "k2": 2}

    def test_string_conflict_prefers_longer(self) -> None:
        merged, conflict = merge_dicts_deterministic(
            {"note": FAKE_BLURB_SHORT},
            {"note": FAKE_BLURB_LONG},
        )
        assert conflict
        assert merged["note"] == FAKE_BLURB_LONG

    def test_identical_strings_no_conflict(self) -> None:
        merged, conflict = merge_dicts_deterministic({"t": "same"}, {"t": "same"})
        assert not conflict
        assert merged["t"] == "same"

    def test_non_string_overwrite_marks_conflict(self) -> None:
        merged, conflict = merge_dicts_deterministic({"n": 1}, {"n": 2})
        assert conflict
        assert merged["n"] == 2

    def test_empty_inputs(self) -> None:
        assert merge_dicts_deterministic(None, None) == ({}, False)
        m, c = merge_dicts_deterministic({}, {"z": 0})
        assert not c and m == {"z": 0}


class TestCosineSimilarity:
    def test_same_direction_is_one(self) -> None:
        assert cosine_similarity([3.0, 4.0], [6.0, 8.0]) == pytest.approx(1.0)

    def test_orthogonal_is_zero(self) -> None:
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_empty_or_mismatch_returns_zero(self) -> None:
        assert cosine_similarity([], [1.0]) == 0.0
        assert cosine_similarity([1.0, 2.0], [1.0]) == 0.0


class TestConnectorGating:
    def test_parses_csv_with_spaces(self) -> None:
        s = structured_connector_set(" PostgreSQL , clickhouse ")
        assert s == {"postgresql", "clickhouse"}

    def test_empty_csv(self) -> None:
        assert structured_connector_set("") == set()
        assert structured_connector_set(None) == set()

    def test_allowlist_behavior(self) -> None:
        csv = "postgresql,clickhouse"
        assert not is_semantic_merge_allowed_for_connector(
            "PostgreSQL", merge_enabled=True, structured_connectors_csv=csv
        )
        assert is_semantic_merge_allowed_for_connector(
            "gmail", merge_enabled=True, structured_connectors_csv=csv
        )
        assert not is_semantic_merge_allowed_for_connector(
            "gmail", merge_enabled=False, structured_connectors_csv=csv
        )


class TestEmbeddingTextHash:
    def test_stable_for_same_string(self) -> None:
        s = "fake embedding source text"
        assert embedding_text_hash(s) == embedding_text_hash(s)

    def test_different_inputs_differ(self) -> None:
        assert embedding_text_hash("a") != embedding_text_hash("b")


class TestSynthesizeSummaryIfNeeded:
    async def test_deterministic_path_without_settings(self) -> None:
        async def boom(_: str) -> str:
            raise AssertionError("LLM must not run")

        out = await synthesize_summary_if_needed(
            title=FAKE_COMPANY,
            text_a=FAKE_BLURB_SHORT,
            text_b=FAKE_BLURB_LONG,
            llm_call=boom,
            llm_synthesis_on_conflict=False,
        )
        assert out == FAKE_BLURB_LONG

    async def test_llm_path_uses_fake_response(self) -> None:
        async def fake_llm(prompt: str) -> str:
            assert FAKE_COMPANY in prompt
            return "synthetic one-liner"

        out = await synthesize_summary_if_needed(
            title=FAKE_COMPANY,
            text_a="Version A text.",
            text_b="Version B text.",
            llm_call=fake_llm,
            llm_synthesis_on_conflict=True,
        )
        assert out == "synthetic one-liner"

    async def test_identical_text_skips_llm(self) -> None:
        async def boom(_: str) -> str:
            raise AssertionError("LLM must not run")

        same = "Duplicate line."
        out = await synthesize_summary_if_needed(
            title="x",
            text_a=same,
            text_b=same,
            llm_call=boom,
            llm_synthesis_on_conflict=True,
        )
        assert out == same
