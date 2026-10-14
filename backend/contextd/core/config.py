"""Configuration settings for the ContextD backend.

Wraps environment variables and provides defaults.
"""

from pathlib import Path
from typing import ClassVar, Optional

from pydantic import PostgresDsn, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings

from contextd.core import semantic_merge_gating


class Settings(BaseSettings):
    """Pydantic settings class.

    Attributes:
    ----------
        PROJECT_NAME (str): The name of the project.
        LOCAL_DEVELOPMENT (bool): Whether the application is running locally.
        LOCAL_CURSOR_DEVELOPMENT (bool): Whether cursor development features are enabled.
        ENVIRONMENT (str): The deployment environment (local, dev, test, prod).
        FRONTEND_LOCAL_DEVELOPMENT_PORT (int): Port for local frontend development.
        FIRST_SUPERUSER (str): The email address of the first superuser.
        FIRST_SUPERUSER_PASSWORD (str): The password of the first superuser.
        ENCRYPTION_KEY (str): The encryption key.
        STATE_SECRET (str): The HMAC secret for OAuth state token signing.
        CODE_SUMMARIZER_ENABLED (bool): Whether the code summarizer is enabled.
        DEBUG (bool): Whether debug mode is enabled.
        LOG_LEVEL (str): The logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        SHOW_LLM_PROMPT (bool): When True, log redacted LLM prompt diagnostics.
        LLM_PROVIDER (str): Provider used by the ContextD LLM gateway.
        LLM_DEFAULT_MODEL (str): Default model used when a role-specific model is not set.
        USE_TOON (bool): When True, encode prompt context as TOON before sending to LLM; logs show TOON output.
        POSTGRES_HOST (str): The PostgreSQL server hostname.
        POSTGRES_DB (str): The PostgreSQL database name.
        POSTGRES_USER (str): The PostgreSQL username.
        POSTGRES_PASSWORD (str): The PostgreSQL password.
        SQLALCHEMY_ASYNC_DATABASE_URI (Optional[PostgresDsn]): The SQLAlchemy async database URI.
        LOCAL_NGROK_SERVER (Optional[str]): The local ngrok server URL.
        RUN_ALEMBIC_MIGRATIONS (bool): Whether to run the alembic migrations.
        RUN_DB_SYNC (bool): Whether to run the system sync to process sources,
            destinations, and entity types.
        REDIS_HOST (str): The Redis server hostname.
        REDIS_PORT (int): The Redis server port.
        REDIS_PASSWORD (Optional[str]): The Redis password (if authentication is enabled).
        REDIS_DB (int): The Redis database number.
        OPENAI_API_KEY (Optional[str]): The OpenAI API key.
        MISTRAL_API_KEY (Optional[str]): The Mistral AI API key.
        FIRECRAWL_API_KEY (Optional[str]): The FireCrawl API key.
        TEMPORAL_HOST (str): The host of the Temporal server.
        TEMPORAL_PORT (int): The Temporal server port.
        TEMPORAL_NAMESPACE (str): The namespace of the Temporal server.
        TEMPORAL_TASK_QUEUE (str): The task queue for the Temporal server.
        TEMPORAL_ENABLED (bool): Whether Temporal is enabled.
        SYNC_MAX_WORKERS (int): The maximum number of workers for sync tasks.
        SYNC_THREAD_POOL_SIZE (int): The size of the thread pool for sync tasks.
        WEB_FETCHER_MAX_CONCURRENT (int): Max concurrent web scraping requests
        OPENAI_MAX_CONCURRENT (int): Max concurrent OpenAI API requests
        CTTI_MAX_CONCURRENT (int): Max concurrent CTTI (ClinicalTrials.gov) requests
        USE_GRAPH_EVENTS (bool): Enable Phase 2 knowledge graph event generation system
        STRIPE_DEVELOPER_MONTHLY: str = ""
        STRIPE_PRO_MONTHLY: str = ""
        STRIPE_TEAM_MONTHLY: str = ""
        STRIPE_ENTERPRISE_MONTHLY: str = ""

        # Custom deployment URLs
        API_FULL_URL (Optional[str]): The full URL for the API.
        ADDITIONAL_CORS_ORIGINS (Optional[list[str]]): Additional CORS origins separated by commas.
    """

    LOCAL_ENVIRONMENTS: ClassVar[set[str]] = {"local", "test"}
    HARDENED_ENVIRONMENTS: ClassVar[set[str]] = {
        "dev",
        "stg",
        "prd",
        "self-hosted",
    }
    ENVIRONMENT_ALIASES: ClassVar[dict[str, str]] = {
        "development": "dev",
        "stage": "stg",
        "staging": "stg",
        "prod": "prd",
        "production": "prd",
        "testing": "test",
        "self_hosted": "self-hosted",
        "selfhosted": "self-hosted",
    }
    WEAK_SECRET_VALUES: ClassVar[set[str]] = {
        "",
        "admin",
        "changeme",
        "contextd",
        "contextd1234",
        "password",
        "contextd-dev-password",
        "dev-secret-key-change-in-production",
    }
    MIN_PRODUCTION_SECRET_LENGTH: ClassVar[int] = 32
    UNSAFE_STORAGE_PATHS: ClassVar[set[str]] = {
        "/",
        "/tmp",
        "/var",
        "/var/lib",
        "/etc",
        "/usr",
        "/home",
        "/Users",
    }

    PROJECT_NAME: str = "ContextD"
    LOCAL_DEVELOPMENT: bool = False
    LOCAL_CURSOR_DEVELOPMENT: bool = False
    ENVIRONMENT: str = "local"
    FRONTEND_LOCAL_DEVELOPMENT_PORT: int = 8080
    BACKEND_PORT: int = 8001

    # Rate limiting
    DISABLE_RATE_LIMIT: bool = False  # For testing purposes - disables rate limiting completely
    FIRST_SUPERUSER: str
    FIRST_SUPERUSER_PASSWORD: str

    AUTH_ENABLED: Optional[bool] = False
    DEV_AUTH: bool = (
        False  # When True, enables local email+password auth (requires AUTH_ENABLED=false)
    )
    DEV_AUTH_SECRET_KEY: str = "dev-secret-key-change-in-production"
    DEV_AUTH_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours
    AUTH0_DOMAIN: Optional[str] = None
    AUTH0_AUDIENCE: Optional[str] = None
    AUTH0_RULE_NAMESPACE: Optional[str] = None
    AUTH0_CLIENT_ID: Optional[str] = None  # SPA Client ID
    AUTH0_M2M_CLIENT_ID: Optional[str] = None  # Machine-to-Machine Client ID for Management API
    AUTH0_M2M_CLIENT_SECRET: Optional[str] = None  # Machine-to-Machine Client Secret

    ENCRYPTION_KEY: str

    # OAuth state HMAC secret for CSRF protection
    # Must be a strong, random secret in production
    STATE_SECRET: str

    CODE_SUMMARIZER_ENABLED: bool = False

    # Debug configuration
    DEBUG: bool = False

    # Logging configuration
    LOG_LEVEL: str = "INFO"

    # Graph chat: when True, log redacted prompt diagnostics in the backend.
    SHOW_LLM_PROMPT: bool = False

    # Central ContextD LLM gateway configuration. Role-specific values preserve current
    # behavior while moving model policy out of individual call sites.
    LLM_PROVIDER: str = "openai"
    LLM_DEFAULT_MODEL: str = "gpt-4o-mini"
    LLM_EXTRACTION_MODEL: Optional[str] = None
    LLM_ANSWER_SYNTHESIS_MODEL: Optional[str] = "gpt-4o"
    LLM_AGENT_MODEL: Optional[str] = "gpt-4o"
    LLM_PROPERTY_SYNTHESIS_MODEL: Optional[str] = None
    LLM_SCHEMA_MODEL: Optional[str] = None
    LLM_TOKENIZER: str = "o200k_base"
    LLM_CONTEXT_WINDOW: int = 128000
    LLM_COMPLETION_TIMEOUT_SECONDS: float = 120.0
    LLM_STRUCTURED_OUTPUT_TIMEOUT_SECONDS: float = 120.0
    LLM_EMBEDDING_TIMEOUT_SECONDS: float = 300.0
    LLM_MAX_ATTEMPTS: int = 2
    LLM_RETRY_BACKOFF_SECONDS: float = 0.5
    LLM_EMBEDDING_MODEL_1536: str = "text-embedding-3-small"
    LLM_EMBEDDING_MODEL_3072: str = "text-embedding-3-large"
    LLM_EMBEDDING_TOKENIZER: str = "cl100k_base"
    LLM_EMBEDDING_MAX_TOKENS: int = 8192
    CONTEXT_FORGE_AI_ENABLED: bool = True
    CONTEXT_FORGE_AI_MAX_OBJECTS: int = 12
    CONTEXT_FORGE_AI_MAX_COLUMNS_PER_OBJECT: int = 24

    # Search/indexing live path. Neo4j fulltext is the default retrieval index for fresh setup.
    SEARCH_INDEX_BACKEND: str = "neo4j-fulltext"
    USE_ENTITY_INDEXING: bool = True

    # When True, encode prompt context as TOON (Token-Oriented Object Notation) before sending to LLM
    USE_TOON: bool = True

    POSTGRES_HOST: str
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "contextd"
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_SSLMODE: str = "prefer"  # disable for PgBouncer, require for Azure PostgreSQL
    SQLALCHEMY_ASYNC_DATABASE_URI: Optional[PostgresDsn] = None

    LOCAL_NGROK_SERVER: Optional[str] = None

    RUN_ALEMBIC_MIGRATIONS: bool = True
    RUN_DB_SYNC: bool = True
    ENABLE_INTERNAL_SOURCES: bool = False  # Enable internal/testing sources (stub, snapshot)

    # Redis configuration
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: Optional[str] = None
    REDIS_DB: int = 0

    # Storage configuration (filesystem-based, cloud-agnostic)
    STORAGE_PATH: str = "./local_storage"  # In K8s: /data/contextd-storage (PVC mount)

    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    MISTRAL_API_KEY: Optional[str] = None
    FIRECRAWL_API_KEY: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None
    COHERE_API_KEY: Optional[str] = None
    CEREBRAS_API_KEY: Optional[str] = None
    AZURE_KEYVAULT_NAME: Optional[str] = None

    # Temporal configuration
    TEMPORAL_HOST: str = "localhost"
    TEMPORAL_PORT: int = 7233
    TEMPORAL_NAMESPACE: str = "default"
    TEMPORAL_TASK_QUEUE: str = "contextd-sync-queue"
    TEMPORAL_ENABLED: bool = False
    TEMPORAL_DISABLE_SANDBOX: bool = False

    # Temporal worker graceful shutdown configuration
    TEMPORAL_GRACEFUL_SHUTDOWN_TIMEOUT: int = 7200  # 2 hours in seconds
    WORKER_METRICS_PORT: int = 8888  # Port for /drain and /health endpoints

    # Stripe billing settings
    STRIPE_ENABLED: bool = False
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""

    STRIPE_DEVELOPER_MONTHLY: str = ""
    STRIPE_PRO_MONTHLY: str = ""
    STRIPE_PRO_YEARLY: str = ""
    STRIPE_TEAM_MONTHLY: str = ""
    STRIPE_TEAM_YEARLY: str = ""
    STRIPE_ENTERPRISE_MONTHLY: str = ""
    STRIPE_YEARLY_DISCOUNT_COUPON_ID: str = ""

    # Email settings - only for production ContextD instance
    SENDGRID_API_KEY: Optional[str] = None
    SENDGRID_FROM_EMAIL: Optional[str] = None

    # Donke integration (internal automation service)
    DONKE_URL: Optional[str] = None
    DONKE_API_KEY: Optional[str] = None

    # Source configurations via Environment Variables
    # These allow auto-configuring sources on startup
    GITHUB_ACCESS_TOKEN: Optional[str] = None
    GITHUB_REPOSITORY_NAME: Optional[str] = None
    SLACK_ACCESS_TOKEN: Optional[str] = None
    NOTION_ACCESS_TOKEN: Optional[str] = None
    LINEAR_API_KEY: Optional[str] = None
    ASANA_ACCESS_TOKEN: Optional[str] = None
    GOOGLE_ACCESS_TOKEN: Optional[str] = None
    GMAIL_ACCESS_TOKEN: Optional[str] = None
    GOOGLE_CALENDAR_ACCESS_TOKEN: Optional[str] = None
    GOOGLE_DOCS_ACCESS_TOKEN: Optional[str] = None
    OUTLOOK_CALENDAR_ACCESS_TOKEN: Optional[str] = None
    # Postgres source connector (direct auth — needs full connection details)
    POSTGRES_SOURCE_HOST: Optional[str] = None
    POSTGRES_SOURCE_PORT: int = 5432
    POSTGRES_SOURCE_DB: Optional[str] = None
    POSTGRES_SOURCE_USER: Optional[str] = None
    POSTGRES_SOURCE_PASSWORD: Optional[str] = None
    POSTGRES_SOURCE_SCHEMA: str = "public"
    POSTGRES_SOURCE_TABLES: str = "*"
    # ClickHouse source connector (clickhouse_connect: host, user, password, secure)
    CLICKHOUSE_SOURCE_HOST: Optional[str] = None
    CLICKHOUSE_SOURCE_USER: str = "default"
    CLICKHOUSE_SOURCE_PASSWORD: str = ""
    CLICKHOUSE_SOURCE_SECURE: bool = True
    CLICKHOUSE_SOURCE_DB: str = "default"
    CLICKHOUSE_SOURCE_TABLES: str = "*"

    # PostHog Analytics Configuration
    # Public API key for open source and hosted platform
    POSTHOG_API_KEY: str = ""
    POSTHOG_HOST: str = "https://eu.i.posthog.com"
    # Analytics is opt-in. Hosted deployments should set ANALYTICS_ENABLED=true explicitly.
    ANALYTICS_ENABLED: bool = False

    # Sync configuration — tuned for high-memory servers (lower workers/batches if timeouts or OOM)
    SYNC_MAX_WORKERS: int = 12
    SYNC_THREAD_POOL_SIZE: int = 128
    # Large batches and queue = fewer round-trips, more in-flight work (use memory for throughput)
    SYNC_BATCH_SIZE: int = 160  # Entities per micro-batch submitted to workers
    SYNC_INDEX_BATCH_SIZE: int = 128  # Entities per embedding/upsert batch in IndexHandler
    SYNC_QUEUE_SIZE: int = (
        50_000  # Stream producer queue (backpressure buffer between source and workers)
    )
    SYNC_DB_POOL_SIZE: Optional[int] = (
        None  # If set, use as Postgres pool_size/max_overflow (high-memory)
    )
    WEB_FETCHER_MAX_CONCURRENT: int = 16  # Max concurrent web scraping requests
    OPENAI_MAX_CONCURRENT: int = 32  # Max concurrent OpenAI API requests (embedding throughput)
    CTTI_MAX_CONCURRENT: int = 3  # Max concurrent CTTI (ClinicalTrials.gov) requests

    # Phase 2: Knowledge Graph Event Generation
    USE_GRAPH_EVENTS: bool = False  # Enable graph event generation system

    # Two-Phase Graph Commit Architecture
    # When enabled, graph events are written to PostgreSQL first (Phase 1),
    # then committed atomically to Neo4j after all batches complete (Phase 2)
    USE_TWO_PHASE_GRAPH_COMMIT: bool = False

    # Semantic entity merge (LightRAG-style dedup; PersonNode merge runs for all connectors when True)
    SEMANTIC_MERGE_ENABLED: bool = False
    """When True, run semantic merge before graph events.

    **PersonNode** (including LLM-folded ``*:Person`` extractions): alias + vector + optional LLM
    for **every** connector so people share one graph id across sources.

    **Global** merge of non-person entities into the shared pool runs only for connectors *not*
    listed in ``SEMANTIC_MERGE_STRUCTURED_CONNECTORS`` (unstructured).
    """

    SEMANTIC_MERGE_SHADOW_MODE: bool = False
    """When True, compute merge decisions and log only; do not persist alias rows or mutate normalized entities."""

    SEMANTIC_MERGE_SIMILARITY_THRESHOLD: float = 0.7
    """Minimum cosine similarity for vector candidate shortlist (within the same entity_type)."""

    SEMANTIC_MERGE_TOP_K: int = 5
    """Max vector similarity candidates to consider before LLM judge."""

    SEMANTIC_MERGE_LLM_JUDGE_ENABLED: bool = True
    """Use LLM to confirm top vector candidate is the same real-world entity."""

    SEMANTIC_MERGE_LLM_SYNTHESIS_ON_CONFLICT: bool = True
    """When property merge has conflicts, use LLM to synthesize compact summary text."""

    SEMANTIC_MERGE_STRUCTURED_CONNECTORS: str = "postgresql,clickhouse"
    """Comma-separated connection short_name values treated as structured DB sources.

    They **skip global** semantic merge of source rows (orders, tickets, …) into the unstructured
    pool; **PersonNode** merge still runs when ``SEMANTIC_MERGE_ENABLED`` is True.

    Also used by graph chat: GLM agents run only when every connection in the collection is listed here.
    """

    # Azure storage config for non-local environments (auto-resolved from ENVIRONMENT)
    AZURE_STORAGE_ACCOUNT_NAME: Optional[str] = None  # Auto-resolved if not set
    AZURE_RAW_DATA_CONTAINER: str = "raw"  # Container for raw data

    API_REQUEST_BODY_SIZE_LIMIT: int = 10 * 1024 * 1024  # 10MB default
    API_REQUEST_TIMEOUT_SECONDS: int = 180

    # Custom deployment URLs - these are used to override the default URLs to allow
    # for custom domains in custom deployments
    API_FULL_URL: Optional[str] = None
    APP_FULL_URL: Optional[str] = None
    ADDITIONAL_CORS_ORIGINS: Optional[list[str]] = None  # Separated by commas or semicolons

    @field_validator("ENVIRONMENT", mode="before")
    def normalize_environment(cls, v: Optional[str]) -> str:
        """Normalize environment names to ContextD's supported profiles."""
        environment = str(v or "local").strip().lower().replace("_", "-")
        environment = cls.ENVIRONMENT_ALIASES.get(environment, environment)
        supported = cls.LOCAL_ENVIRONMENTS | cls.HARDENED_ENVIRONMENTS
        if environment not in supported:
            raise ValueError("ENVIRONMENT must be one of: local, test, dev, stg, prd, self-hosted")
        return environment

    @field_validator("LLM_PROVIDER", mode="before")
    def normalize_llm_provider(cls, v: Optional[str]) -> str:
        """Normalize and validate the configured LLM provider name."""
        provider = str(v or "openai").strip().lower().replace("_", "-")
        if provider not in {"openai"}:
            raise ValueError("LLM_PROVIDER must be one of: openai")
        return provider

    @field_validator(
        "LLM_DEFAULT_MODEL",
        "LLM_TOKENIZER",
        "LLM_EMBEDDING_MODEL_1536",
        "LLM_EMBEDDING_MODEL_3072",
        "LLM_EMBEDDING_TOKENIZER",
        mode="before",
    )
    def validate_required_llm_text(cls, v: Optional[str], info: ValidationInfo) -> str:
        """Ensure required LLM gateway text settings are not blank."""
        value = str(v or "").strip()
        if not value:
            raise ValueError(f"{info.field_name} must not be empty")
        return value

    @field_validator("LLM_CONTEXT_WINDOW", "LLM_EMBEDDING_MAX_TOKENS", "LLM_MAX_ATTEMPTS")
    def validate_positive_llm_integer(cls, v: int, info: ValidationInfo) -> int:
        """Ensure LLM token/window settings are positive."""
        if v <= 0:
            raise ValueError(f"{info.field_name} must be positive")
        return v

    @field_validator(
        "LLM_COMPLETION_TIMEOUT_SECONDS",
        "LLM_STRUCTURED_OUTPUT_TIMEOUT_SECONDS",
        "LLM_EMBEDDING_TIMEOUT_SECONDS",
        "LLM_RETRY_BACKOFF_SECONDS",
    )
    def validate_llm_timing_settings(cls, v: float, info: ValidationInfo) -> float:
        """Ensure LLM timeout and retry settings are bounded."""
        if info.field_name == "LLM_RETRY_BACKOFF_SECONDS":
            if v < 0:
                raise ValueError("LLM_RETRY_BACKOFF_SECONDS must not be negative")
            return v
        if v <= 0:
            raise ValueError(f"{info.field_name} must be positive")
        return v

    @field_validator("SEARCH_INDEX_BACKEND", mode="before")
    def validate_search_index_backend(cls, v: Optional[str]) -> str:
        """Ensure the current search/indexing live path is explicit."""
        backend = str(v or "neo4j-fulltext").strip().lower().replace("_", "-")
        if backend != "neo4j-fulltext":
            raise ValueError("SEARCH_INDEX_BACKEND must be neo4j-fulltext")
        return backend

    @field_validator("AZURE_KEYVAULT_NAME", mode="before")
    def validate_azure_keyvault_name(cls, v: Optional[str], info: ValidationInfo) -> Optional[str]:
        """Create a keyvault name based on the environment.

        Like: "contextd-core-dev-kv" or "contextd-core-prd-kv"

        Args:
            v: The Azure KeyVault name.
            info: Validation context containing all field values.
        """
        environment = info.data.get("ENVIRONMENT", "local")
        if environment in ["dev", "prd"] and not v:
            return f"contextd-core-{environment}-kv"
        return v

    @model_validator(mode="after")
    def validate_production_hardening(self) -> "Settings":
        """Fail closed for production-like environments.

        Local and test environments intentionally remain permissive so developers can
        run the app without hosted auth, public domains, or managed storage.
        """
        if self.ENVIRONMENT.lower() in self.LOCAL_ENVIRONMENTS:
            return self

        checks = [
            (not self.AUTH_ENABLED, "AUTH_ENABLED must be true in production-like environments"),
            (self.DEV_AUTH, "DEV_AUTH must be false in production-like environments"),
            (
                self.LOCAL_DEVELOPMENT,
                "LOCAL_DEVELOPMENT must be false in production-like environments",
            ),
            (
                self.LOCAL_CURSOR_DEVELOPMENT,
                "LOCAL_CURSOR_DEVELOPMENT must be false in production-like environments",
            ),
            (self.DEBUG, "DEBUG must be false in production-like environments"),
            (
                self.LOG_LEVEL.upper() == "DEBUG",
                "LOG_LEVEL must not be DEBUG in production-like environments",
            ),
            (
                self.DISABLE_RATE_LIMIT,
                "DISABLE_RATE_LIMIT must be false in production-like environments",
            ),
            (self.SHOW_LLM_PROMPT, "SHOW_LLM_PROMPT must be false in production-like environments"),
            (
                self._is_weak_secret(self.DEV_AUTH_SECRET_KEY),
                "DEV_AUTH_SECRET_KEY must be strong and must not use a development default",
            ),
            (
                self._is_weak_secret(self.ENCRYPTION_KEY),
                "ENCRYPTION_KEY must be strong and must not use a development default",
            ),
            (
                self._is_weak_secret(self.STATE_SECRET),
                "STATE_SECRET must be strong and must not use a development default",
            ),
            (
                self.POSTGRES_PASSWORD in self.WEAK_SECRET_VALUES,
                "POSTGRES_PASSWORD must not use a development default",
            ),
            (
                self.FIRST_SUPERUSER_PASSWORD in self.WEAK_SECRET_VALUES,
                "FIRST_SUPERUSER_PASSWORD must not use a development default",
            ),
            (
                bool(self.ADDITIONAL_CORS_ORIGINS) and "*" in self.ADDITIONAL_CORS_ORIGINS,
                "ADDITIONAL_CORS_ORIGINS must not contain '*'",
            ),
            (not self.API_FULL_URL, "API_FULL_URL must be set in production-like environments"),
            (not self.APP_FULL_URL, "APP_FULL_URL must be set in production-like environments"),
            (
                self._storage_path_error() is not None,
                self._storage_path_error() or "STORAGE_PATH is unsafe",
            ),
            (
                self.ANALYTICS_ENABLED and not self.POSTHOG_API_KEY,
                "POSTHOG_API_KEY must be set when ANALYTICS_ENABLED is true",
            ),
            (
                self.ANALYTICS_ENABLED and not self.POSTHOG_HOST,
                "POSTHOG_HOST must be set when ANALYTICS_ENABLED is true",
            ),
        ]
        errors = [message for failed, message in checks if failed]

        if errors:
            raise ValueError("; ".join(errors))

        return self

    def _is_weak_secret(self, value: Optional[str]) -> bool:
        """Return True when a production secret is empty, short, or a known default."""
        secret = (value or "").strip()
        return secret in self.WEAK_SECRET_VALUES or len(secret) < self.MIN_PRODUCTION_SECRET_LENGTH

    def _storage_path_error(self) -> Optional[str]:
        """Return an actionable error when production storage points somewhere unsafe."""
        raw_path = (self.STORAGE_PATH or "").strip()
        if not raw_path:
            return "STORAGE_PATH must be set in production-like environments"

        storage_path = Path(raw_path).expanduser()
        if any(part == ".." for part in storage_path.parts):
            return "STORAGE_PATH must not contain parent-directory traversal"

        if not storage_path.is_absolute():
            return "STORAGE_PATH must be absolute in production-like environments"

        resolved_path = storage_path.resolve(strict=False)
        if str(resolved_path) in self.UNSAFE_STORAGE_PATHS:
            return "STORAGE_PATH must point to a dedicated ContextD data directory"

        return None

    @field_validator("ADDITIONAL_CORS_ORIGINS", mode="before")
    def parse_cors_origins(cls, v: Optional[str | list[str]]) -> Optional[list[str]]:
        """Parse CORS origins from string to list, supporting both comma and semicolon separators.

        Args:
            v: The CORS origins string or list.

        Returns:
            Optional[list[str]]: The parsed list of CORS origins or None.
        """
        if isinstance(v, list) or v is None:
            return v

        normalized = v.replace(";", ",")
        return [origin.strip() for origin in normalized.split(",") if origin.strip()]

    @field_validator(
        "AUTH0_DOMAIN",
        "AUTH0_AUDIENCE",
        "AUTH0_RULE_NAMESPACE",
        "AUTH0_CLIENT_ID",
        "AUTH0_M2M_CLIENT_ID",
        "AUTH0_M2M_CLIENT_SECRET",
        mode="before",
    )
    def validate_auth0_settings(cls, v: str, info: ValidationInfo) -> str:
        """Validate Auth0 settings when AUTH_ENABLED is True.

        Args:

        ----
            v (str): The value of the Auth0 setting.
            info (ValidationInfo): The validation context containing all field values.

        Returns:
        -------
            str: The validated Auth0 setting.

        Raises:
        ------
            ValueError: If AUTH_ENABLED is True and the Auth0 setting is empty.
        """
        auth_enabled = info.data.get("AUTH_ENABLED", False)
        if auth_enabled and not v:
            field_name = info.field_name
            raise ValueError(f"{field_name} must be set when AUTH_ENABLED is True")
        return v

    @field_validator(
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "STRIPE_DEVELOPER_MONTHLY",
        "STRIPE_PRO_MONTHLY",
        "STRIPE_TEAM_MONTHLY",
        mode="before",
    )
    def validate_stripe_settings(cls, v: str, info: ValidationInfo) -> str:
        """Validate Stripe settings when STRIPE_ENABLED is True.

        Raises a ValueError if any required Stripe setting is missing while
        billing is enabled, to ensure misconfigurations fail fast at startup.
        """
        stripe_enabled = info.data.get("STRIPE_ENABLED", False)
        if stripe_enabled and not v:
            field_name = info.field_name
            raise ValueError(f"{field_name} must be set when STRIPE_ENABLED is True")
        return v

    @field_validator("SENDGRID_FROM_EMAIL", mode="before")
    def validate_sendgrid_email_settings(
        cls, v: Optional[str], info: ValidationInfo
    ) -> Optional[str]:
        """Validate SendGrid email settings when SENDGRID_API_KEY is configured.

        Ensures that SENDGRID_FROM_EMAIL is set when email functionality is enabled,
        preventing accidental use of default values in production.
        """
        sendgrid_api_key = info.data.get("SENDGRID_API_KEY")
        if sendgrid_api_key and not v:
            raise ValueError("SENDGRID_FROM_EMAIL must be set when SENDGRID_API_KEY is configured")
        return v

    @field_validator("STATE_SECRET", mode="before")
    def validate_state_secret(cls, v: str, info: ValidationInfo) -> str:
        """Validate the STATE_SECRET has minimum required length.

        Args:
            v: The STATE_SECRET value.
            info: Validation context containing all field values.

        Returns:
            str: The validated STATE_SECRET.

        Raises:
            ValueError: If STATE_SECRET is not set or too short.
        """
        if not v or len(v) < 32:
            raise ValueError(
                "STATE_SECRET must be at least 32 characters long. "
                "Generate a strong secret using: "
                "python -c 'import secrets; print(secrets.token_urlsafe(32))'"
            )
        return v

    @field_validator("SQLALCHEMY_ASYNC_DATABASE_URI", mode="before")
    def assemble_db_connection(cls, v: Optional[str], info: ValidationInfo) -> PostgresDsn:
        """Build the SQLAlchemy database URI.

        Args:
        ----
            v (Optional[str]): The value of the SQLALCHEMY_DATABASE_URI setting.
            info (ValidationInfo): The validation context containing all field values.

        Returns:
        -------
            PostgresDsn: The assembled SQLAlchemy async database URI.

        """
        if isinstance(v, str):
            return v

        # Connect to local PostgreSQL server during local development
        # This allows developers to debug without Docker
        host = info.data.get("POSTGRES_HOST", "localhost")
        port = info.data.get("POSTGRES_PORT", 5432)

        return PostgresDsn.build(
            scheme="postgresql+asyncpg",
            username=info.data.get("POSTGRES_USER"),
            password=info.data.get("POSTGRES_PASSWORD"),
            host=host,
            port=port,
            path=f"{info.data.get('POSTGRES_DB') or ''}",
        )

    @property
    def api_url(self) -> str:
        """The server URL.

        Returns:
            str: The server URL.
        """
        if self.API_FULL_URL:
            return self.API_FULL_URL

        if self.ENVIRONMENT == "local":
            return self.LOCAL_NGROK_SERVER or f"http://localhost:{self.BACKEND_PORT}"
        if self.ENVIRONMENT == "prd":
            return "https://api.contextd.local"
        return f"https://api.{self.ENVIRONMENT}.contextd.local"

    @property
    def app_url(self) -> str:
        """The app URL.

        Returns:
            str: The app URL.
        """
        if self.APP_FULL_URL:
            return self.APP_FULL_URL

        if self.ENVIRONMENT == "local":
            return f"http://localhost:{self.FRONTEND_LOCAL_DEVELOPMENT_PORT}"
        if self.ENVIRONMENT == "prd":
            return "https://app.contextd.local"
        return f"https://app.{self.ENVIRONMENT}.contextd.local"

    @property
    def docs_url(self) -> str:
        """The docs URL.

        Returns:
            str: The docs URL.
        """
        if self.ENVIRONMENT == "local":
            return f"http://localhost:{self.FRONTEND_LOCAL_DEVELOPMENT_PORT}"
        if self.ENVIRONMENT == "prd":
            return "https://docs.contextd.local"
        return f"https://docs.{self.ENVIRONMENT}.contextd.local"

    @property
    def temporal_address(self) -> str:
        """The Temporal server address.

        Returns:
            str: The Temporal server address in host:port format.
        """
        return f"{self.TEMPORAL_HOST}:{self.TEMPORAL_PORT}"

    def semantic_merge_structured_connector_set(self) -> set[str]:
        """Connection short names that skip semantic merge (structured DB sources)."""
        return semantic_merge_gating.structured_connector_set(
            self.SEMANTIC_MERGE_STRUCTURED_CONNECTORS
        )

    def is_semantic_merge_allowed_for_connector(self, short_name: str) -> bool:
        """True when semantic merge is enabled and connector is not structured-only."""
        return semantic_merge_gating.is_semantic_merge_allowed_for_connector(
            short_name,
            merge_enabled=self.SEMANTIC_MERGE_ENABLED,
            structured_connectors_csv=self.SEMANTIC_MERGE_STRUCTURED_CONNECTORS,
        )


settings = Settings()
