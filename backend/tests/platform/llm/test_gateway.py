"""Tests for the ContextD LLM gateway."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

os.environ.setdefault("FIRST_SUPERUSER", "admin@contextd.local")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "strong-admin-password")
os.environ.setdefault("ENCRYPTION_KEY", "x" * 44)
os.environ.setdefault("STATE_SECRET", "s" * 32)
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_USER", "contextd")
os.environ.setdefault("POSTGRES_PASSWORD", "strong-postgres-password")


def _settings(**overrides: Any) -> SimpleNamespace:
    base = SimpleNamespace(
        LLM_PROVIDER="openai",
        LLM_DEFAULT_MODEL="default-model",
        LLM_EXTRACTION_MODEL=None,
        LLM_ANSWER_SYNTHESIS_MODEL="answer-model",
        LLM_AGENT_MODEL="agent-model",
        LLM_PROPERTY_SYNTHESIS_MODEL=None,
        LLM_SCHEMA_MODEL=None,
        LLM_TOKENIZER="cl100k_base",
        LLM_CONTEXT_WINDOW=128000,
        LLM_COMPLETION_TIMEOUT_SECONDS=120.0,
        LLM_STRUCTURED_OUTPUT_TIMEOUT_SECONDS=120.0,
        LLM_EMBEDDING_TIMEOUT_SECONDS=300.0,
        LLM_MAX_ATTEMPTS=2,
        LLM_RETRY_BACKOFF_SECONDS=0.0,
        LLM_EMBEDDING_MODEL_1536="embedding-small",
        LLM_EMBEDDING_MODEL_3072="embedding-large",
        LLM_EMBEDDING_TOKENIZER="cl100k_base",
        LLM_EMBEDDING_MAX_TOKENS=8192,
        OPENAI_API_KEY="test-api-key",
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def _ctx(records: list[dict[str, Any]] | None = None) -> SimpleNamespace:
    def _record(level: str):
        def _log(*args: Any, **kwargs: Any) -> None:
            if records is not None:
                records.append({"level": level, "args": args, "kwargs": kwargs})

        return _log

    logger = SimpleNamespace(
        debug=_record("debug"),
        info=_record("info"),
        warning=_record("warning"),
    )
    return SimpleNamespace(logger=logger)


def test_configured_llm_model_uses_role_override_then_default() -> None:
    from contextd.platform.llm.gateway import configured_llm_model

    settings = _settings(LLM_EXTRACTION_MODEL="extract-model")

    assert configured_llm_model("extraction", settings) == "extract-model"
    assert configured_llm_model("property_synthesis", settings) == "default-model"
    assert configured_llm_model("answer_synthesis", settings) == "answer-model"


def test_gateway_builds_model_spec_from_configured_role() -> None:
    from contextd.platform.llm.gateway import ContextDLLMGateway

    gateway = ContextDLLMGateway(_settings(LLM_SCHEMA_MODEL="schema-model"))

    spec = gateway.model_spec("schema_extraction")

    assert spec.llm_model is not None
    assert spec.llm_model.name == "schema-model"
    assert spec.llm_model.tokenizer == "cl100k_base"
    assert spec.llm_model.context_window == 128000


def test_gateway_builds_embedding_spec_from_configured_dimensions() -> None:
    from contextd.platform.llm.gateway import ContextDLLMGateway

    gateway = ContextDLLMGateway(_settings())

    large = gateway.embedding_model_config(3072)
    small = gateway.embedding_model_config(768)

    assert large.name == "embedding-large"
    assert large.dimensions == 3072
    assert small.name == "embedding-small"
    assert small.dimensions == 1536


def test_gateway_requires_configured_api_key() -> None:
    from contextd.platform.llm.gateway import ContextDLLMGateway, LLMConfigurationError

    gateway = ContextDLLMGateway(_settings(OPENAI_API_KEY=""))

    with pytest.raises(LLMConfigurationError, match="OPENAI_API_KEY"):
        gateway.create_provider(ctx=_ctx())


@pytest.mark.asyncio
async def test_complete_routes_through_configured_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    from contextd.platform.llm.gateway import ContextDLLMGateway

    captured: dict[str, Any] = {}

    class FakeProvider:
        def __init__(self, api_key: str, model_spec: Any, ctx: Any) -> None:
            captured["api_key"] = api_key
            captured["model_spec"] = model_spec
            captured["ctx"] = ctx

        async def generate(self, messages: list[dict[str, str]]) -> str:
            captured["messages"] = messages
            return "gateway-response"

    monkeypatch.setattr("contextd.platform.llm.gateway.OpenAIProvider", FakeProvider)

    gateway = ContextDLLMGateway(_settings(LLM_EXTRACTION_MODEL="extract-model"))
    result = await gateway.complete(
        [{"role": "user", "content": "hello"}],
        role="extraction",
        ctx=_ctx(),
    )

    assert result == "gateway-response"
    assert captured["api_key"] == "test-api-key"
    assert captured["model_spec"].llm_model.name == "extract-model"
    assert captured["messages"][0]["content"] == "hello"


@pytest.mark.asyncio
async def test_complete_wraps_provider_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    from contextd.platform.llm.gateway import ContextDLLMGateway, LLMProviderError

    calls = 0

    class FailingProvider:
        def __init__(self, api_key: str, model_spec: Any, ctx: Any) -> None:
            pass

        async def generate(self, messages: list[dict[str, str]]) -> str:
            nonlocal calls
            calls += 1
            raise RuntimeError("sdk exploded while handling secret-from-prompt")

    monkeypatch.setattr("contextd.platform.llm.gateway.OpenAIProvider", FailingProvider)

    gateway = ContextDLLMGateway(_settings())
    with pytest.raises(LLMProviderError, match="LLM completion failed") as exc_info:
        await gateway.complete(
            [{"role": "user", "content": "secret-from-prompt"}],
            role="answer_synthesis",
            ctx=_ctx(),
        )

    assert calls == 1
    assert "RuntimeError" in str(exc_info.value)
    assert "secret-from-prompt" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_complete_retries_retryable_provider_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextd.platform.llm.gateway import ContextDLLMGateway

    calls = 0

    class FlakyProvider:
        def __init__(self, api_key: str, model_spec: Any, ctx: Any) -> None:
            pass

        async def generate(self, messages: list[dict[str, str]]) -> str:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("429 rate limit")
            return "recovered"

    monkeypatch.setattr("contextd.platform.llm.gateway.OpenAIProvider", FlakyProvider)

    gateway = ContextDLLMGateway(_settings(LLM_MAX_ATTEMPTS=2))
    result = await gateway.complete(
        [{"role": "user", "content": "hello"}],
        role="answer_synthesis",
        ctx=_ctx(),
    )

    assert result == "recovered"
    assert calls == 2


@pytest.mark.asyncio
async def test_complete_times_out_with_typed_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from contextd.platform.llm.gateway import ContextDLLMGateway, LLMTimeoutError

    class SlowProvider:
        def __init__(self, api_key: str, model_spec: Any, ctx: Any) -> None:
            pass

        async def generate(self, messages: list[dict[str, str]]) -> str:
            await asyncio.sleep(0.05)
            return "too late"

    monkeypatch.setattr("contextd.platform.llm.gateway.OpenAIProvider", SlowProvider)

    gateway = ContextDLLMGateway(
        _settings(LLM_COMPLETION_TIMEOUT_SECONDS=0.001, LLM_MAX_ATTEMPTS=1)
    )

    with pytest.raises(LLMTimeoutError, match="timed out"):
        await gateway.complete(
            [{"role": "user", "content": "hello"}],
            role="answer_synthesis",
            ctx=_ctx(),
        )


@pytest.mark.asyncio
async def test_complete_logs_redacted_telemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    from contextd.platform.llm.gateway import ContextDLLMGateway

    class FakeProvider:
        def __init__(self, api_key: str, model_spec: Any, ctx: Any) -> None:
            pass

        async def generate(self, messages: list[dict[str, str]]) -> str:
            return "ok"

    monkeypatch.setattr("contextd.platform.llm.gateway.OpenAIProvider", FakeProvider)
    records: list[dict[str, Any]] = []

    gateway = ContextDLLMGateway(_settings())
    result = await gateway.complete(
        [{"role": "user", "content": "super-sensitive-prompt"}],
        role="answer_synthesis",
        ctx=_ctx(records),
    )

    assert result == "ok"
    assert records
    assert "super-sensitive-prompt" not in str(records)
    dimensions = records[-1]["kwargs"]["extra"]["custom_dimensions"]
    assert dimensions["prompt_redacted"] is True
    assert dimensions["llm_status"] == "success"
    assert dimensions["llm_input_chars"] == len("super-sensitive-prompt")


def test_redact_llm_messages_hides_content() -> None:
    from contextd.platform.llm.gateway import redact_llm_messages

    redacted = redact_llm_messages(
        [
            {"role": "system", "content": "system-secret"},
            {"role": "user", "content": "user-secret"},
        ]
    )

    assert redacted[0]["role"] == "system"
    assert redacted[0]["content"].startswith("<redacted")
    assert "chars=" in redacted[0]["content"]
    assert "system-secret" not in str(redacted)
    assert "user-secret" not in str(redacted)


def test_gateway_rejects_unsupported_provider() -> None:
    from contextd.platform.llm.gateway import ContextDLLMGateway, LLMConfigurationError

    gateway = ContextDLLMGateway(_settings(LLM_PROVIDER="unsupported"))

    with pytest.raises(LLMConfigurationError, match="Unsupported LLM_PROVIDER"):
        gateway.provider_name()


def test_source_tree_has_no_direct_gpt_model_hardcodes() -> None:
    """Current model defaults live in config; runtime calls use the gateway."""
    source_root = Path(__file__).resolve().parents[3] / "contextd"
    allowed = {
        source_root / "core" / "config.py",
    }
    forbidden = ["gpt-" + "4o-mini", "gpt-" + "4o"]

    offenders: list[str] = []
    for path in source_root.rglob("*.py"):
        if path in allowed:
            continue
        text = path.read_text()
        for model in forbidden:
            if model in text:
                offenders.append(f"{path.relative_to(source_root)}: {model}")

    assert offenders == []
