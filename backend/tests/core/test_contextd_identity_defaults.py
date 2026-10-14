"""Tests for ContextD runtime naming defaults."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("FIRST_SUPERUSER", "admin@contextd.local")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "strong-admin-password")
os.environ.setdefault("ENCRYPTION_KEY", "x" * 44)
os.environ.setdefault("STATE_SECRET", "s" * 32)
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_USER", "contextd")
os.environ.setdefault("POSTGRES_PASSWORD", "strong-postgres-password")


def test_organization_auth0_name_uses_contextd_prefix() -> None:
    """New hosted-auth organization names use the ContextD identity."""
    from contextd.core.organization_service import OrganizationService

    name = OrganizationService()._create_org_name(SimpleNamespace(name="Acme Corp"))

    assert re.fullmatch(r"contextd-acme-corp-[a-f0-9]{8}", name)


def test_graph_defaults_use_contextd_names(monkeypatch) -> None:
    """Fresh graph config defaults do not expose old runtime identifiers."""
    monkeypatch.delenv("GRAPH_GDS_GRAPH_NAME", raising=False)
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)

    from contextd.platform.graph.config import GraphConfig

    config = GraphConfig()

    assert config.gds_graph_name == "contextd_graph"
    assert config.password == "contextd-dev-password"


def test_structured_logs_use_contextd_names() -> None:
    """Structured log records expose ContextD names, not temporary package paths."""
    from contextd.core.logging import JSONFormatter

    record = logging.LogRecord(
        name="contextd.core.example",
        level=logging.INFO,
        pathname="/app/contextd/core/example.py",
        lineno=10,
        msg="hello",
        args=(),
        exc_info=None,
    )

    payload = json.loads(JSONFormatter().format(record))

    assert payload["logger"] == "contextd.core.example"
    assert payload["module"] == "contextd.core.example"


def test_domain_exception_base_uses_contextd_name() -> None:
    """Domain exceptions expose the ContextD base type."""
    import contextd.core.exceptions as exceptions
    from contextd.core.exceptions import ContextDException, PermissionException

    assert issubclass(PermissionException, ContextDException)
    assert not hasattr(exceptions, "Air" + "weave" + "Exception")


def test_contextd_field_helper_replaces_legacy_field_identity() -> None:
    """Entity field metadata helpers expose only ContextD names."""
    import importlib.util

    import contextd.core.shared_models as shared_models
    import contextd.platform.entities._contextd_field as field_module
    from contextd.core.shared_models import ContextDFieldFlag
    from contextd.platform.entities._contextd_field import ContextDField

    field_info = ContextDField(..., is_entity_id=True, embeddable=True, description="ID")

    assert field_info.json_schema_extra == {
        "embeddable": True,
        "is_entity_id": True,
    }
    assert ContextDFieldFlag.IS_ENTITY_ID.value == "is_entity_id"
    assert not hasattr(shared_models, "Air" + "weave" + "FieldFlag")
    assert not hasattr(field_module, "Air" + "weave" + "Field")
    old_module = "contextd.platform.entities._" + "air" + "weave" + "_field"

    assert importlib.util.find_spec(old_module) is None


def test_contextd_field_identity_sources_do_not_expose_legacy_names() -> None:
    """Live field metadata modules do not carry the old helper identity."""
    repo = Path(os.environ.get("CONTEXTD_REPO_ROOT", Path(__file__).resolve().parents[3]))
    files = [
        *sorted((repo / "backend/contextd/platform/entities").glob("*.py")),
        repo / "backend/contextd/core/shared_models.py",
        repo / "backend/contextd/platform/configs/database/schema.py",
        repo / "backend/contextd/platform/sync/entity_pipeline.py",
        repo / "backend/contextd/platform/sync/pipeline/hash_computer.py",
        repo / "backend/contextd/platform/sync/pipeline/text_builder.py",
        repo / "backend/contextd/platform/sync/state/field_hasher.py",
        repo / "backend/contextd/search/operations/query_interpretation.py",
    ]
    forbidden_terms = (
        "Air" + "weave" + "Field",
        "Air" + "weave" + "FieldFlag",
        "_air" + "weave" + "_field",
    )

    for path in files:
        content = path.read_text(encoding="utf-8")
        for term in forbidden_terms:
            assert term not in content, f"{path.relative_to(repo)} still contains {term}"


def test_contextd_http_client_wrapper_replaces_legacy_identity() -> None:
    """Source HTTP client wrapping exposes only ContextD names."""
    import importlib.util
    from uuid import uuid4

    import contextd.platform.http_client.contextd_client as client_module
    from contextd.platform.http_client import ContextDHttpClient
    from contextd.platform.utils.source_factory_utils import wrap_source_with_contextd_client

    class WrappedClient:
        timeout = None
        is_closed = False

        async def aclose(self) -> None:
            return None

    class Source:
        def __init__(self) -> None:
            self._wrapped_client = WrappedClient()
            self._http_client_factory = lambda **_: self._wrapped_client
            self.factory = None

        def set_http_client_factory(self, factory) -> None:
            self.factory = factory

    class Logger:
        def __init__(self) -> None:
            self.messages = []

        def debug(self, message: str) -> None:
            self.messages.append(message)

    source = Source()
    logger = Logger()
    ctx = SimpleNamespace(
        organization=SimpleNamespace(id=uuid4()),
        has_feature=lambda _feature: True,
    )

    wrap_source_with_contextd_client(
        source=source,
        source_short_name="gmail",
        source_connection_id=uuid4(),
        ctx=ctx,
        logger=logger,
    )

    client = source.factory()
    old_module = "contextd.platform.http_client." + "air" + "weave" + "_client"

    assert isinstance(client, ContextDHttpClient)
    assert client._client is source._wrapped_client
    assert any("ContextDHttpClient configured" in message for message in logger.messages)
    assert not hasattr(client_module, "Air" + "weave" + "HttpClient")
    assert importlib.util.find_spec(old_module) is None


def test_contextd_http_client_identity_sources_do_not_expose_legacy_names() -> None:
    """Live HTTP client modules do not carry the old wrapper identity."""
    repo = Path(os.environ.get("CONTEXTD_REPO_ROOT", Path(__file__).resolve().parents[3]))
    files = [
        repo / "backend/contextd/core/exceptions.py",
        repo / "backend/contextd/platform/builders/source.py",
        repo / "backend/contextd/platform/http_client/__init__.py",
        repo / "backend/contextd/platform/http_client/contextd_client.py",
        repo / "backend/contextd/platform/sources/asana.py",
        repo / "backend/contextd/platform/sources/google_drive.py",
        repo / "backend/contextd/platform/sources/retry_helpers.py",
        repo / "backend/contextd/platform/utils/source_factory_utils.py",
        repo / "backend/contextd/search/factory.py",
    ]
    forbidden_terms = (
        "Air" + "weave" + "HttpClient",
        "wrap_source_with_" + "air" + "weave" + "_client",
        "air" + "weave" + "_client",
    )

    for path in files:
        content = path.read_text(encoding="utf-8")
        for term in forbidden_terms:
            assert term not in content, f"{path.relative_to(repo)} still contains {term}"


def test_backend_live_sources_do_not_expose_capitalized_legacy_product_name() -> None:
    """Backend source/doc text does not expose the old capitalized product identity."""
    repo = Path(os.environ.get("CONTEXTD_REPO_ROOT", Path(__file__).resolve().parents[3]))
    root = repo / "backend/contextd"
    checked_suffixes = {".py", ".md"}
    forbidden = "Air" + "weave"

    for path in sorted(root.rglob("*")):
        if path.suffix not in checked_suffixes:
            continue

        content = path.read_text(encoding="utf-8")
        assert forbidden not in content, f"{path.relative_to(repo)} still contains {forbidden}"


def test_examples_do_not_expose_legacy_product_identity() -> None:
    """Checked-in examples must not advertise stale product, SDK, or hosted API names."""
    repo = Path(os.environ.get("CONTEXTD_REPO_ROOT", Path(__file__).resolve().parents[3]))
    examples_root = repo / "examples"
    checked_suffixes = {".ipynb", ".md", ".py"}
    forbidden_terms = (
        "Air" + "weave",
        "air" + "weave",
        "AIR" + "WEAVE",
        "docs." + "air" + "weave",
        "app." + "air" + "weave",
        "api." + "air" + "weave",
    )

    if not examples_root.exists():
        return

    for path in sorted(examples_root.rglob("*")):
        if not path.is_file() or path.suffix not in checked_suffixes:
            continue

        content = path.read_text(encoding="utf-8")
        for term in forbidden_terms:
            assert term not in content, f"{path.relative_to(repo)} still contains {term}"


def test_public_identity_surfaces_use_contextd_names() -> None:
    """Public runtime/configuration surfaces do not expose the old product identity."""
    repo = Path(os.environ.get("CONTEXTD_REPO_ROOT", Path(__file__).resolve().parents[3]))
    public_files = [
        "backend/contextd/api/deps.py",
        "backend/contextd/integrations/auth0_management.py",
        "backend/contextd/__init__.py",
        "backend/contextd/core/exceptions.py",
        "frontend/src/lib/theme-provider.tsx",
        "frontend/serve.json",
        "frontend/package.json",
    ]
    forbidden_terms = (
        "Air" + "weave",
        "AIR" + "WEAVE",
        "Air" + "weave" + " Platform",
        "Air" + "weave" + "Exception",
        "air" + "weave-ai",
        "air" + "weave-frontend",
        "x-" + "air" + "weave",
        "air" + "weave" + "-ui-theme",
        "docs." + "air" + "weave",
        "app." + "air" + "weave",
        "api." + "air" + "weave",
        "dev-" + "air" + "weave",
        "stg-" + "air" + "weave",
    )

    for relative_path in public_files:
        content = (repo / relative_path).read_text(encoding="utf-8")
        for term in forbidden_terms:
            assert term not in content, f"{relative_path} still contains {term}"


def test_public_markdown_docs_use_contextd_identity() -> None:
    """Public markdown documentation and plans do not carry stale product identity."""
    repo = Path(os.environ.get("CONTEXTD_REPO_ROOT", Path(__file__).resolve().parents[3]))
    markdown_files = [
        *sorted((repo / "docs").rglob("*.md")),
    ]
    forbidden_terms = (
        "Air" + "weave",
        "air" + "weave",
        "AIR" + "WEAVE",
        "air" + "weave-ai",
        "docs." + "air" + "weave",
        "app." + "air" + "weave",
        "api." + "air" + "weave",
    )

    for path in markdown_files:
        if not path.exists():
            continue

        content = path.read_text(encoding="utf-8")
        for term in forbidden_terms:
            assert term not in content, f"{path.relative_to(repo)} still contains {term}"


def test_root_helper_scripts_do_not_expose_legacy_public_identity() -> None:
    """Root helper scripts are either removed or use ContextD public names."""
    repo = Path(os.environ.get("CONTEXTD_REPO_ROOT", Path(__file__).resolve().parents[3]))
    forbidden_terms = (
        "Air" + "weave",
        "AIR" + "WEAVE",
        "air" + "weave-ai",
        "docs." + "air" + "weave",
        "app." + "air" + "weave",
        "api." + "air" + "weave",
    )

    for path in sorted(repo.glob("*.py")):
        if not path.is_file():
            continue

        content = path.read_text(encoding="utf-8")
        for term in forbidden_terms:
            assert term not in content, f"{path.relative_to(repo)} still contains {term}"
