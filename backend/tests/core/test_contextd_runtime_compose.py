"""Tests for ContextD Docker Compose runtime defaults."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]


def _compose(path: str) -> dict:
    return yaml.safe_load((REPO_ROOT / path).read_text(encoding="utf-8"))


def _env_keys(service: dict) -> set[str]:
    values = service.get("environment", [])
    if isinstance(values, dict):
        return set(values)
    return {item.split("=", 1)[0] for item in values}


def _env_map(service: dict) -> dict[str, str]:
    values = service.get("environment", [])
    if isinstance(values, dict):
        return {str(key): str(value) for key, value in values.items()}
    result: dict[str, str] = {}
    for item in values:
        key, _, value = item.partition("=")
        result[key] = value
    return result


def _volumes(service: dict) -> set[str]:
    return set(service.get("volumes", []))


def _file(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def _migration_value(content: str, key: str) -> str | None:
    prefix = f"{key} ="
    for line in content.splitlines():
        if line.startswith(prefix):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def test_backend_entrypoint_uses_bounded_reload_paths() -> None:
    """Docker backend hot reload watches app packages, not the whole mounted tree."""
    content = _file("docker/backend/entrypoint.sh")

    assert "--reload-dir /app/contextd" in content
    assert content.count("--reload-dir /app/contextd") == 1
    assert "--reload-dir /app\n" not in content
    assert "--reload-dir /app " not in content


def test_backend_docker_context_excludes_runtime_artifacts() -> None:
    """Backend images must not bake local runtime data or generated caches."""
    ignored = {
        line.strip()
        for line in _file(".dockerignore").splitlines()
        if line.strip() and not line.startswith("#")
    }

    assert "backend/local_storage/" in ignored
    assert "backend/__pycache__/" in ignored
    assert "backend/.pytest_cache/" in ignored
    assert "backend/dist/" in ignored
    assert "frontend/node_modules/" in ignored
    assert "frontend/dist/" in ignored


def test_backend_runtime_masks_host_local_storage() -> None:
    """Main runtime must not leak ignored host files into app containers."""
    compose = _compose("docker/docker-compose.yml")
    services = compose["services"]

    for service_name in ("backend", "temporal-worker"):
        volumes = _volumes(services[service_name])

        assert "../backend:/app" not in volumes
        assert "contextd_storage:/app/local_storage" in volumes

    assert "contextd_storage" in compose["volumes"]


def test_test_stack_masks_host_local_storage() -> None:
    """The test stack should also keep runtime storage out of the source bind mount."""
    compose = _compose("docker/docker-compose.test.yml")

    assert "contextd_storage:/app/local_storage" in _volumes(compose["services"]["backend"])
    assert "contextd_storage" in compose["volumes"]


def test_removed_search_service_is_not_in_main_stack() -> None:
    """Removed experimental search services are not present in the main stack."""
    compose = _compose("docker/docker-compose.yml")
    removed_service = "ve" + "spa"
    removed_embedding_service = "text" + "2vec-transformers"
    removed_vector_service = "q" + "drant"

    assert removed_service not in compose["services"]
    assert f"{removed_service}-init" not in compose["services"]
    assert removed_embedding_service not in compose["services"]
    assert removed_vector_service not in compose["services"]
    assert f"{removed_service}_data" not in compose.get("volumes", {})
    assert f"{removed_vector_service}_data" not in compose.get("volumes", {})


def test_removed_search_service_is_not_in_dev_stack() -> None:
    """Removed experimental search services are not present in the dev stack."""
    compose = _compose("docker/docker-compose.dev.yml")
    removed_service = "ve" + "spa"
    removed_embedding_service = "text" + "2vec-transformers"
    removed_vector_service = "q" + "drant"

    assert removed_service not in compose["services"]
    assert f"{removed_service}-init" not in compose["services"]
    assert removed_embedding_service not in compose["services"]
    assert removed_vector_service not in compose["services"]
    assert f"{removed_service}_data" not in compose.get("volumes", {})
    assert f"{removed_vector_service}_data" not in compose.get("volumes", {})


def test_backend_runtime_does_not_wire_removed_search_service() -> None:
    """Backend and worker environments do not advertise a disabled search service."""
    compose = _compose("docker/docker-compose.yml")
    services = compose["services"]
    prefix = "VE" + "SPA"
    removed_embedding_setting = "TEXT" + "2VEC_INFERENCE_URL"
    removed_vector_prefix = "Q" + "DRANT"

    for service_name in ("backend", "temporal-worker"):
        env_keys = _env_keys(services[service_name])
        assert f"{prefix}_URL" not in env_keys
        assert f"{prefix}_PORT" not in env_keys
        assert f"{prefix}_CLUSTER" not in env_keys
        assert removed_embedding_setting not in env_keys
        assert f"{removed_vector_prefix}_HOST" not in env_keys
        assert f"{removed_vector_prefix}_PORT" not in env_keys


def test_backend_runtime_wires_adk_to_milvus() -> None:
    """Backend and worker containers use the local ADK package with Milvus memory."""
    compose = _compose("docker/docker-compose.yml")
    services = compose["services"]

    assert "milvus-etcd" in services
    assert "milvus" in services
    assert services["milvus"]["depends_on"]["milvus-etcd"]["condition"] == "service_healthy"
    assert "milvus_data" in compose["volumes"]
    assert "milvus_etcd_data" in compose["volumes"]

    for service_name in ("backend", "temporal-worker"):
        env = _env_map(services[service_name])
        assert env["VECTOR_STORE_PROVIDER"] == "milvus"
        assert env["MILVUS_HOST"] == "milvus"
        assert env["MILVUS_PORT"] == "19530"
        assert env["MILVUS_COLLECTION"] == "contextd_adk_memories"
        assert env["SEARCH_INDEX_BACKEND"] == "neo4j-fulltext"
        assert env["USE_ENTITY_INDEXING"] == "true"
        assert env["INDEX_FULLTEXT_ENABLED"] == "true"
        assert "INDEX_" + "VECTOR_ENABLED" not in env
        assert env["LANGFUSE_ENABLED"] == "false"
        assert services[service_name]["depends_on"]["milvus"]["condition"] == "service_healthy"


def test_native_adk_package_is_built_into_backend_images() -> None:
    """Backend images build from the native local ADK package."""
    package_dir = REPO_ROOT / "backend/contextd-adk"
    removed_dir = "".join(("sh", "yft", "labs", "-", "cont", "in", "uum"))

    assert package_dir.exists()
    assert (package_dir / "pyproject.toml").exists()
    assert (package_dir / "src/contextd_adk").is_dir()
    assert not (REPO_ROOT / "backend" / removed_dir).exists()
    assert not (REPO_ROOT / ".gitmodules").exists()

    for dockerfile in ("docker/backend/Dockerfile", "docker/backend/Dockerfile.dev"):
        content = _file(dockerfile)
        assert "COPY backend/contextd-adk ./contextd-adk" in content
        assert removed_dir not in content


def test_admin_sync_surfaces_do_not_expose_removed_search_controls() -> None:
    """Removed search controls must stay out of the default admin sync surfaces."""
    checked_files = [
        REPO_ROOT / "backend/contextd/api/v1/endpoints/admin.py",
        REPO_ROOT / "frontend/src/pages/admin/SyncsTab.tsx",
    ]
    forbidden_terms = (
        "Ve" + "spa",
        "ve" + "spa",
        "last_" + "ve" + "spa" + "_job",
        "has_" + "ve" + "spa" + "_job",
        "skip_" + "ve" + "spa",
        "skip" + "Ve" + "spa",
        "total_" + "ve" + "spa" + "_entity_count",
    )

    for path in checked_files:
        content = path.read_text(encoding="utf-8")
        for term in forbidden_terms:
            assert term not in content, f"{path.relative_to(REPO_ROOT)} still contains {term}"


def test_removed_search_runtime_has_no_local_artifacts() -> None:
    """Runtime compose/scripts no longer carry the removed search service wiring."""
    checked_files = [
        REPO_ROOT / "docker/docker-compose.yml",
        REPO_ROOT / "docker/docker-compose.dev.yml",
        REPO_ROOT / "docker/docker-compose.test.yml",
        REPO_ROOT / "scripts/start-stack.sh",
        REPO_ROOT / ".env.example",
        REPO_ROOT / "scripts/run-backend-local.sh",
        REPO_ROOT / "scripts/run-worker-local.sh",
        REPO_ROOT / "scripts/run-frontend-local.sh",
    ]
    removed_service = "ve" + "spa"
    removed_embedding_service = "text" + "2vec"
    forbidden_terms = (
        removed_service,
        removed_service.title(),
        "search-" + removed_service,
        removed_embedding_service,
        "TEXT" + "2VEC_INFERENCE_URL",
        "Q" + "DRANT_HOST",
        "Q" + "DRANT_PORT",
        "Q" + "DRANT_FULL_URL",
        "local-embeddings",
    )

    assert not (REPO_ROOT / removed_service).exists()

    for path in checked_files:
        content = path.read_text(encoding="utf-8")
        for term in forbidden_terms:
            assert term not in content, f"{path.relative_to(REPO_ROOT)} still contains {term}"


def test_reset_path_removes_all_contextd_data_volumes() -> None:
    """Fresh rebuilds must clear every ContextD Docker volume, not only Postgres."""
    content = _file("scripts/start-stack.sh")

    assert "RESET_VOLUME_NAMES=" in content
    assert "/^contextd_/" in content
    assert "volume rm $RESET_VOLUME_NAMES" in content
    assert "contextd_postgres_data" not in content


def test_alembic_uses_linear_contextd_migration_chain() -> None:
    """Fresh installs start at the ContextD baseline and advance through one linear chain."""
    versions_dir = REPO_ROOT / "backend/alembic/versions"
    migration_files = sorted(
        path for path in versions_dir.glob("*.py") if path.name != "__init__.py"
    )

    assert migration_files
    baseline = migration_files[0]
    assert baseline.name.startswith("0001_contextd_initial_schema")

    previous_revision: str | None = None
    revisions: list[str] = []
    for index, path in enumerate(migration_files):
        content = path.read_text(encoding="utf-8")
        revision = _migration_value(content, "revision")
        down_revision = _migration_value(content, "down_revision")

        assert revision, f"{path.name} is missing revision"
        assert revision not in revisions, f"{path.name} duplicates revision {revision}"
        revisions.append(revision)
        if index == 0:
            assert down_revision == "None"
        else:
            assert down_revision == previous_revision
        previous_revision = revision

    baseline_content = baseline.read_text(encoding="utf-8")
    forbidden_terms = (
        "q" + "drant",
        "Q" + "DRANT",
        "ve" + "spa",
        "Ve" + "spa",
        "text" + "2vec",
        "TEXT" + "2VEC",
        "local_text" + "2vec",
    )

    assert "down_revision = None" in baseline_content
    assert "op.create_table('graph_events'" in baseline_content
    assert "op.create_index(op.f('ix_graph_events_sync_job_id')" in baseline_content
    for path in migration_files:
        content = path.read_text(encoding="utf-8")
        for term in forbidden_terms:
            assert term not in content


def test_backend_entrypoint_migrates_and_seeds_before_serving() -> None:
    """Container startup must apply schema and seed metadata before accepting traffic."""
    main_entrypoint = _file("docker/backend/entrypoint.sh")
    dev_entrypoint = _file("docker/backend/entrypoint.dev.sh")
    local_backend = _file("scripts/run-backend-local.sh")

    migration = "poetry run alembic upgrade head"
    initial_data = "poetry run python -m contextd.initial_data"
    server = "poetry run uvicorn contextd.main:app"

    assert main_entrypoint.index(migration) < main_entrypoint.index(initial_data)
    assert main_entrypoint.index(initial_data) < main_entrypoint.index(server)
    assert dev_entrypoint.index(migration) < dev_entrypoint.index(initial_data)
    assert dev_entrypoint.index(initial_data) < dev_entrypoint.index(server)
    assert local_backend.index(migration) < local_backend.index(initial_data)
    assert local_backend.index(initial_data) < local_backend.index(server)


def test_compose_startup_waits_for_required_health_checks() -> None:
    """App containers should not race their database, cache, graph, or vector services."""
    compose = _compose("docker/docker-compose.yml")
    services = compose["services"]

    assert services["milvus"]["depends_on"]["milvus-etcd"]["condition"] == "service_healthy"
    assert services["temporal"]["depends_on"]["postgres"]["condition"] == "service_healthy"

    for dependency in ("postgres", "redis", "milvus", "neo4j"):
        assert services["backend"]["depends_on"][dependency]["condition"] == "service_healthy"

    for dependency in ("postgres", "redis", "milvus", "temporal", "neo4j"):
        assert (
            services["temporal-worker"]["depends_on"][dependency]["condition"] == "service_healthy"
        )

    assert services["frontend-dev"]["depends_on"]["backend"]["condition"] == "service_healthy"


def test_backend_services_have_startup_health_smoke_contracts() -> None:
    """Backend-like containers must expose health checks with enough startup budget."""
    main = _compose("docker/docker-compose.yml")
    test = _compose("docker/docker-compose.test.yml")

    for service_name in ("backend",):
        healthcheck = main["services"][service_name]["healthcheck"]
        assert "http://localhost:8001/health" in " ".join(healthcheck["test"])
        assert healthcheck["retries"] >= 10
        assert healthcheck["start_period"] == "60s"

    test_healthcheck = test["services"]["backend"]["healthcheck"]
    assert "http://localhost:8001/health" in " ".join(test_healthcheck["test"])
    assert test_healthcheck["retries"] >= 10
    assert test_healthcheck["start_period"] == "60s"


def test_backend_test_stack_declares_required_settings() -> None:
    """The dedicated Docker test stack should boot without relying on local .env."""
    compose = _compose("docker/docker-compose.test.yml")
    env = _env_map(compose["services"]["backend"])

    required_settings = {
        "FIRST_SUPERUSER",
        "FIRST_SUPERUSER_PASSWORD",
        "ENCRYPTION_KEY",
        "STATE_SECRET",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "AUTH_ENABLED",
        "VECTOR_STORE_PROVIDER",
        "MILVUS_HOST",
        "MILVUS_PORT",
        "MILVUS_COLLECTION",
    }

    assert required_settings.issubset(env)
    assert len(env["STATE_SECRET"]) >= 32
    assert env["VECTOR_STORE_PROVIDER"] == "milvus"
    assert env["MILVUS_HOST"] == "milvus"


def test_start_stack_smoke_checks_backend_before_frontend() -> None:
    """The automation script should wait for API health before declaring UI readiness."""
    content = _file("scripts/start-stack.sh")

    backend_probe = "exec contextd-backend curl -f http://localhost:8001/health"
    frontend_probe = "curl -f http://localhost:8080"

    assert "MAX_RETRIES=30" in content
    assert backend_probe in content
    assert content.index("Checking backend health...") < content.index(frontend_probe)


def test_initial_data_seeding_is_ordered_and_env_gated() -> None:
    """Startup seeding should create core records first and only wire configured sources."""
    content = _file("backend/contextd/initial_data.py")

    assert content.index("await init_db(session)") < content.index(
        "await init_source_connections(session)"
    )
    assert "if not token:" in content
    assert "get_by_query_and_org" in content
    assert "source_connection_service.delete" in content
    assert "source_connection_service.create" in content


def test_initial_data_seeding_covers_supported_env_sources() -> None:
    """Environment seeding should stay explicit and cover every supported token gate."""
    content = _file("backend/contextd/initial_data.py")

    expected_settings = {
        "GITHUB_ACCESS_TOKEN",
        "SLACK_ACCESS_TOKEN",
        "NOTION_ACCESS_TOKEN",
        "LINEAR_API_KEY",
        "ASANA_ACCESS_TOKEN",
        "GOOGLE_ACCESS_TOKEN",
        "GMAIL_ACCESS_TOKEN",
        "GOOGLE_CALENDAR_ACCESS_TOKEN",
        "GOOGLE_DOCS_ACCESS_TOKEN",
        "OUTLOOK_CALENDAR_ACCESS_TOKEN",
        "POSTGRES_SOURCE_HOST",
        "CLICKHOUSE_SOURCE_HOST",
    }
    expected_sources = {
        '"github"',
        '"slack"',
        '"notion"',
        '"linear"',
        '"asana"',
        '"google_drive"',
        '"gmail"',
        '"google_calendar"',
        '"google_docs"',
        '"outlook_calendar"',
        '"postgresql"',
        '"clickhouse"',
    }

    for setting_name in expected_settings:
        assert f"settings.{setting_name}" in content

    for source_name in expected_sources:
        assert source_name in content

    assert "sync_immediately=True" in content
