"""Helpers for admin sync listing responses."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import ConfigDict

from contextd import schemas


class AdminSyncInfo(schemas.Sync):
    """Extended sync info for admin listing with entity counts and status."""

    total_entity_count: int = 0
    total_arf_entity_count: Optional[int] = None
    total_search_index_entity_count: Optional[int] = None

    last_job_status: Optional[str] = None
    last_job_at: Optional[datetime] = None
    last_job_error: Optional[str] = None
    source_short_name: Optional[str] = None
    source_is_authenticated: Optional[bool] = None
    readable_collection_id: Optional[str] = None

    model_config = ConfigDict(
        from_attributes=True,
    )


def _build_admin_sync_info_list(
    syncs: list,
    sync_connections: dict,
    source_conn_map: dict,
    last_job_map: dict,
    entity_count_map: dict,
    arf_count_map: dict,
    search_index_count_map: dict,
) -> List[AdminSyncInfo]:
    """Build list of AdminSyncInfo from query results."""
    admin_syncs = []
    for sync in syncs:
        conn_info = sync_connections.get(sync.id, {"source": None, "destinations": []})
        source_info = source_conn_map.get(sync.id, {})
        last_job = last_job_map.get(sync.id, {})

        sync_dict = {**sync.__dict__}
        if "_sa_instance_state" in sync_dict:
            sync_dict.pop("_sa_instance_state")

        sync_dict["source_connection_id"] = conn_info["source"]
        sync_dict["destination_connection_ids"] = conn_info["destinations"]
        sync_dict["total_entity_count"] = entity_count_map.get(sync.id, 0)
        sync_dict["total_arf_entity_count"] = arf_count_map.get(sync.id)
        sync_dict["total_search_index_entity_count"] = search_index_count_map.get(sync.id)
        # Handle status - may be enum or string depending on query
        last_status = last_job.get("status")
        sync_dict["last_job_status"] = (
            (last_status.value if hasattr(last_status, "value") else last_status)
            if last_status
            else None
        )
        sync_dict["last_job_at"] = last_job.get("completed_at")
        sync_dict["last_job_error"] = last_job.get("error")
        sync_dict["source_short_name"] = source_info.get("short_name")
        sync_dict["readable_collection_id"] = source_info.get("readable_collection_id")
        sync_dict["source_is_authenticated"] = source_info.get("is_authenticated")

        admin_syncs.append(AdminSyncInfo.model_validate(sync_dict))

    return admin_syncs
