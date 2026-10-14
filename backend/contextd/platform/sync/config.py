"""Sync execution configuration for controlling sync behavior."""

from pydantic import BaseModel, Field


class SyncExecutionConfig(BaseModel):
    """Declarative sync execution configuration.

    Each component reads only the flags it needs - highly modular.
    Config is persisted in sync_job.execution_config_json to avoid Temporal bloat.
    """

    # Handler toggles
    enable_raw_data_handler: bool = Field(True, description="Enable RawDataHandler (ARF)")
    enable_postgres_handler: bool = Field(True, description="Enable EntityPostgresHandler")

    # Behavior flags
    skip_hash_comparison: bool = Field(False, description="Force INSERT for all entities")
    skip_cursor_load: bool = Field(False, description="Don't load cursor (fetch all entities)")
    skip_cursor_updates: bool = Field(
        False, description="Don't save cursor progress (for ARF-only syncs)"
    )
    drift_check_enabled: bool = Field(
        True,
        description="Record source config/schema/cursor drift metadata after sync finalization",
    )
    reset_drift_baseline: bool = Field(
        False,
        description="Promote the current config/schema observation to the drift baseline",
    )

    # ARF replay mode
    replay_from_arf: bool = Field(
        False,
        description="Replay entities from ARF storage instead of calling the source. "
        "Uses the sync's existing ARF data.",
    )

    @classmethod
    def default(cls) -> "SyncExecutionConfig":
        """Normal sync to ARF and Postgres; search indexing is handled separately."""
        return cls()

    @classmethod
    def arf_capture_only(cls) -> "SyncExecutionConfig":
        """Capture to ARF without postgres metadata.

        Fetches all entities (skips cursor) to ensure complete ARF backfill.
        Skips hash comparison to force all entities to be captured, not just changed ones.
        Disables postgres handler so no metadata/hashes are written to database.
        Useful for backfilling ARF storage without impacting production databases.
        """
        return cls(
            enable_postgres_handler=False,
            skip_hash_comparison=True,
            skip_cursor_load=True,
            skip_cursor_updates=True,
        )
