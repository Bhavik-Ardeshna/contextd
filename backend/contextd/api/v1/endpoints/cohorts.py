"""Cohort creation API: draft pipeline, persistence, shallow run, member detail."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Path, Query

from contextd import crud
from contextd.api.context import ApiContext
from contextd.api.deps import get_context
from contextd.api.router import TrailingSlashRouter
from contextd.core.config import settings
from contextd.core.semantic_merge_gating import (
    structured_connector_set,
    use_glm_agents_for_graph_chat,
)
from contextd.db.session import get_db_context
from contextd.platform.agent_orchestration.business_logic import (
    expand_query_for_schema,
    format_pruned_schema,
    retrieve_node_types_for_query,
)
from contextd.platform.agent_orchestration.cohort.listing import run_cohort_glm
from contextd.platform.agent_orchestration.cohort.probe import cohort_column_key_compact
from contextd.platform.agent_orchestration.cohort.scoring import run_cohort_scoring_glm
from contextd.platform.agent_orchestration.tools import graph_sql, node_info
from contextd.platform.agent_orchestration.types import CohortScoringRAgentResponse
from contextd.schemas.cohort import (
    CohortCreate,
    CohortDraftRequest,
    CohortDraftResponse,
    CohortMemberDetailResponse,
    CohortMemberRow,
    CohortOut,
    CohortPlanSchema,
    CohortRunResponse,
    CohortScoringPlanSchema,
    ResearchPlanSchema,
    ScoringComponentSchema,
)

router = TrailingSlashRouter()

_CYPHER_PARAM_RE = re.compile(r"\$([a-zA-Z_][a-zA-Z0-9_]*)")


def _compact_param_stem(s: str) -> str:
    return "".join(c.lower() for c in s if c.isalnum())


def _cypher_param_names(cypher: str) -> set[str]:
    return set(_CYPHER_PARAM_RE.findall(cypher or ""))


def _match_probe_numeric_stat(keys_block: Dict[str, Any], stem: str, stat: str) -> Optional[float]:
    """Match stem to a probed property key; return min/max/mean/pXX from numeric probe entry."""
    if not stem or not keys_block:
        return None
    sc = _compact_param_stem(stem)
    candidates: List[tuple[float, int, bool]] = []
    for pk, entry in keys_block.items():
        if not isinstance(entry, dict) or entry.get("kind") != "numeric":
            continue
        pkc = _compact_param_stem(str(pk))
        v = entry.get(stat)
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        is_exact = pkc == sc
        if is_exact or (sc and (pkc.endswith(sc) or sc in pkc or pkc in sc)):
            candidates.append((fv, len(str(pk)), is_exact))
    if not candidates:
        return None
    candidates.sort(key=lambda t: (not t[2], t[1]))
    return candidates[0][0]


def _infer_param_from_probe_snapshot(pname: str, keys_block: Dict[str, Any]) -> Optional[float]:
    pl = pname.lower()
    stat: Optional[str] = None
    stem = ""
    if pl.startswith("max_"):
        stat, stem = "max", pname[4:]
    elif pl.startswith("min_"):
        stat, stem = "min", pname[4:]
    elif pl.startswith("mean_"):
        stat, stem = "mean", pname[5:]
    elif pl.startswith("avg_"):
        stat, stem = "mean", pname[4:]
    elif pl.startswith("p25_"):
        stat, stem = "p25", pname[4:]
    elif pl.startswith("p50_"):
        stat, stem = "p50", pname[4:]
    elif pl.startswith("p75_"):
        stat, stem = "p75", pname[4:]
    else:
        return None
    if stem.endswith("_id"):
        stem = stem[:-3]
    return _match_probe_numeric_stat(keys_block, stem, stat)


def _runtime_cypher_params(cohort: Any) -> Dict[str, Any]:
    """Parameters for executing saved cohort Cypher (draft used $cutoff, $max_* from probes)."""
    params: Dict[str, Any] = {}
    manual = getattr(cohort, "cypher_params", None)
    if isinstance(manual, dict):
        for k, v in manual.items():
            if k and str(k) != "organization_id":
                params[str(k)] = v

    cypher = getattr(cohort, "cypher_text", None) or ""
    needed = _cypher_param_names(cypher)
    needed.discard("organization_id")

    snapshot = getattr(cohort, "distribution_probe_snapshot", None)
    keys_block = snapshot.get("keys") if isinstance(snapshot, dict) else None
    if not isinstance(keys_block, dict):
        keys_block = {}

    for pname in needed:
        if pname in params:
            continue
        if pname == "cutoff":
            cv = getattr(cohort, "cutoff_value", None)
            if cv is not None:
                params[pname] = float(cv)
            continue
        if pname == "node_type":
            nt = getattr(cohort, "target_node_type", None)
            if nt:
                params[pname] = str(nt)
            continue
        inferred = _infer_param_from_probe_snapshot(pname, keys_block)
        if inferred is not None:
            params[pname] = inferred

    return params


def _node_id_from_row(row: Dict[str, Any]) -> Optional[str]:
    for k, v in row.items():
        if cohort_column_key_compact(str(k)) == "nodeid" and v is not None:
            return str(v)
    return None


def _float_field(row: Dict[str, Any], name: str) -> Optional[float]:
    target = cohort_column_key_compact(name)
    for k, v in row.items():
        if cohort_column_key_compact(str(k)) != target:
            continue
        if v is None:
            return None
        try:
            return float(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
    return None


def _score_breakdown_keys_for_saved_cohort(cohort_row: Any) -> List[str]:
    keys = list(getattr(cohort_row, "score_breakdown_keys", None) or [])
    if keys:
        return keys
    spec = getattr(cohort_row, "scoring_spec", None)
    if not isinstance(spec, dict):
        return []
    out: List[str] = []
    for comp in spec.get("components") or []:
        if not isinstance(comp, dict):
            continue
        pk = (comp.get("property_key") or "").strip()
        if not pk:
            continue
        safe = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in pk)
        out.append(f"comp_{safe}")
    return out


def _scoring_plan_to_schema(sp: CohortScoringRAgentResponse) -> CohortScoringPlanSchema:
    rp = sp.research_plan
    return CohortScoringPlanSchema(
        target_node_type=sp.target_node_type,
        display_property_keys=list(sp.display_property_keys or []),
        identifier_property_keys=list(sp.identifier_property_keys or []),
        missing_data_policy=str(sp.missing_data_policy),
        cutoff_method=str(sp.cutoff_method),
        components=[
            ScoringComponentSchema(
                property_key=c.property_key,
                weight=c.weight,
                direction=str(c.direction),
                normalization=dict(c.normalization or {}),
            )
            for c in sp.components
        ],
        research_plan=ResearchPlanSchema(
            goal=rp.goal,
            steps=rp.steps,
            use_p_agent=rp.use_p_agent,
            p_agent_instruction=rp.p_agent_instruction,
        ),
    )


def _project_shallow_row(
    row: Dict[str, Any],
    display_property_keys: List[str],
    identifier_property_keys: List[str],
) -> CohortMemberRow:
    """Map Cypher row to shallow fields using requested property key names."""
    nid = _node_id_from_row(row)
    if not nid:
        nid = ""
    wanted_order: List[str] = list(
        dict.fromkeys(list(identifier_property_keys) + list(display_property_keys))
    )
    fields: Dict[str, Any] = {}
    row_lower = {
        str(k).lower(): (k, v)
        for k, v in row.items()
        if cohort_column_key_compact(str(k)) != "nodeid"
    }
    for w in wanted_order:
        wl = w.lower()
        if wl in row_lower:
            fields[w] = row_lower[wl][1]
            continue
        for rk, rv in row_lower.items():
            if rk == wl or rk.endswith(f"_{wl}"):
                fields[w] = rv[1]
                break
    for extra in ("final_score", "confidence"):
        if extra in fields:
            continue
        want = cohort_column_key_compact(extra)
        for k, v in row.items():
            if cohort_column_key_compact(str(k)) == want:
                fields[extra] = v
                break
    fs = _float_field(row, "final_score")
    cf = _float_field(row, "confidence")
    return CohortMemberRow(node_id=nid, fields=fields, final_score=fs, confidence=cf)


async def _require_structured_collection(readable_id: str, ctx: ApiContext) -> Any:
    """Return collection if GLM/cohort agents are allowed for this collection."""
    async with get_db_context() as db:
        collection = await crud.collection.get_by_readable_id(db, readable_id=readable_id, ctx=ctx)
        if not collection:
            raise HTTPException(status_code=404, detail="Collection not found")
        conns = await crud.source_connection.get_multi_with_stats(
            db, ctx=ctx, collection_id=readable_id, limit=50
        )
        source_types = [c["short_name"] for c in conns if c.get("short_name")]
        if not use_glm_agents_for_graph_chat(
            source_types,
            settings.SEMANTIC_MERGE_STRUCTURED_CONNECTORS,
        ):
            raise HTTPException(
                status_code=400,
                detail="Cohort creation requires a collection with structured connectors only.",
            )
        return collection


async def _pruned_schema_for_cohort_message(
    message: str,
    ctx: ApiContext,
    collection_ids: List[str],
    structured_short_names: List[str],
) -> str:
    """Schema RAG restricted to structured connector types when possible."""
    expanded = await expand_query_for_schema(message, ctx)
    payloads = await retrieve_node_types_for_query(
        ctx.organization.id,
        expanded,
        ctx,
        collection_ids=collection_ids,
        source_types=None,
        top_k=15,
    )
    if not payloads and structured_short_names:
        payloads = await retrieve_node_types_for_query(
            ctx.organization.id,
            expanded,
            ctx,
            collection_ids=None,
            source_types=structured_short_names,
            top_k=15,
        )
    return format_pruned_schema(payloads)


@router.post("/{readable_id}/cohorts/draft", response_model=CohortDraftResponse)
async def draft_cohort(
    readable_id: str = Path(..., description="Collection readable ID"),
    body: CohortDraftRequest = ...,
    ctx: ApiContext = Depends(get_context),
) -> CohortDraftResponse:
    """Run cohort R-Agent → A-Agent once; return plan + Cypher + sample rows (not saved)."""
    collection = await _require_structured_collection(readable_id, ctx)
    structured_csv = settings.SEMANTIC_MERGE_STRUCTURED_CONNECTORS
    structured_set = structured_connector_set(structured_csv)

    async with get_db_context() as db:
        conns = await crud.source_connection.get_multi_with_stats(
            db, ctx=ctx, collection_id=readable_id, limit=50
        )
    source_types = [s for s in (c.get("short_name") for c in conns) if s]
    structured_short_names = [s for s in source_types if s.strip().lower() in structured_set]

    try:
        pruned_schema = await _pruned_schema_for_cohort_message(
            body.message,
            ctx,
            collection_ids=[readable_id],
            structured_short_names=structured_short_names,
        )
    except Exception as e:
        ctx.logger.warning("Cohort schema RAG failed: %s", e)
        pruned_schema = ""

    if body.mode == "scoring":
        glm = await run_cohort_scoring_glm(
            body.message,
            organization_id=ctx.organization.id,
            collection_id=collection.id,
            ctx=ctx,
            pruned_schema=pruned_schema or None,
            source_type_filter=None,
        )
    else:
        glm = await run_cohort_glm(
            body.message,
            organization_id=ctx.organization.id,
            collection_id=collection.id,
            ctx=ctx,
            pruned_schema=pruned_schema or None,
            source_type_filter=None,
        )

    if glm.error and not glm.cohort_plan and not glm.scoring_plan:
        return CohortDraftResponse(mode=body.mode, error=glm.error)

    plan_out: Optional[CohortPlanSchema] = None
    if glm.cohort_plan:
        cp = glm.cohort_plan
        rp = cp.research_plan
        plan_out = CohortPlanSchema(
            target_node_type=cp.target_node_type,
            display_property_keys=cp.display_property_keys,
            identifier_property_keys=cp.identifier_property_keys,
            research_plan=ResearchPlanSchema(
                goal=rp.goal,
                steps=rp.steps,
                use_p_agent=rp.use_p_agent,
                p_agent_instruction=rp.p_agent_instruction,
            ),
        )

    scoring_out: Optional[CohortScoringPlanSchema] = None
    if glm.scoring_plan:
        scoring_out = _scoring_plan_to_schema(glm.scoring_plan)

    return CohortDraftResponse(
        mode=body.mode,
        cohort_plan=plan_out,
        scoring_plan=scoring_out,
        distribution_summary=glm.distribution_summary,
        score_distribution=glm.score_distribution,
        cutoff_value=glm.cutoff_value,
        cutoff_rationale=glm.cutoff_rationale,
        cutoff_iterations_used=glm.cutoff_iterations_used or 0,
        cypher_query=glm.cypher_query,
        sample_rows=glm.sample_rows or [],
        error=glm.error,
        warning=glm.warning,
    )


@router.post("/{readable_id}/cohorts", response_model=CohortOut)
async def create_cohort_saved(
    readable_id: str = Path(...),
    body: CohortCreate = ...,
    ctx: ApiContext = Depends(get_context),
) -> CohortOut:
    """Persist an approved cohort definition."""
    collection = await _require_structured_collection(readable_id, ctx)
    async with get_db_context() as db:
        payload = {**body.model_dump(), "collection_id": collection.id}
        obj = await crud.cohort.create(db, obj_in=payload, ctx=ctx)
        return CohortOut.model_validate(obj)


@router.get("/{readable_id}/cohorts", response_model=List[CohortOut])
async def list_cohorts(
    readable_id: str = Path(...),
    ctx: ApiContext = Depends(get_context),
    skip: int = 0,
    limit: int = 50,
) -> List[CohortOut]:
    """List saved cohorts for a collection."""
    collection = await _require_structured_collection(readable_id, ctx)
    async with get_db_context() as db:
        rows = await crud.cohort.get_multi_for_collection(
            db,
            collection_id=collection.id,
            ctx=ctx,
            skip=skip,
            limit=limit,
        )
        return [CohortOut.model_validate(r) for r in rows]


@router.post("/{readable_id}/cohorts/{cohort_id}/run", response_model=CohortRunResponse)
async def run_cohort_members(
    readable_id: str = Path(...),
    cohort_id: UUID = Path(...),
    ctx: ApiContext = Depends(get_context),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
) -> CohortRunResponse:
    """Execute stored Cypher and return shallow rows (slice for pagination)."""
    collection = await _require_structured_collection(readable_id, ctx)
    async with get_db_context() as db:
        c = await crud.cohort.get_for_collection(
            db,
            cohort_id=cohort_id,
            collection_id=collection.id,
            ctx=ctx,
        )

    max_fetch = min(offset + limit, 500)
    rows = await graph_sql(
        c.cypher_text,
        ctx.organization.id,
        ctx,
        params=_runtime_cypher_params(c),
        max_results=max_fetch,
        readable_collection_id=readable_id,
    )
    slice_rows = rows[offset : offset + limit]
    out_rows = [
        _project_shallow_row(
            r,
            c.display_property_keys or [],
            c.identifier_property_keys or [],
        )
        for r in slice_rows
        if isinstance(r, dict)
    ]
    return CohortRunResponse(
        rows=out_rows,
        total_fetched=len(rows),
        offset=offset,
        limit=limit,
    )


async def _scoring_member_detail_extras(
    cohort_row: Any,
    node_id: str,
    ctx: ApiContext,
    readable_id: str,
) -> tuple[Dict[str, Any], Optional[float], Optional[float]]:
    """Load score breakdown from stored cohort Cypher rows when cohort_mode is scoring."""
    keys = _score_breakdown_keys_for_saved_cohort(cohort_row)
    rows_probe: List[Dict[str, Any]] = []
    try:
        rows_probe = await graph_sql(
            cohort_row.cypher_text,
            ctx.organization.id,
            ctx,
            params=_runtime_cypher_params(cohort_row),
            max_results=5000,
            readable_collection_id=readable_id,
        )
    except Exception as e:
        ctx.logger.warning("member-detail scoring row lookup failed: %s", e)
    target = next(
        (r for r in rows_probe if isinstance(r, dict) and _node_id_from_row(r) == node_id),
        None,
    )
    if not isinstance(target, dict):
        return {}, None, None
    breakdown: Dict[str, Any] = {}
    for bk in keys:
        for tk, tv in target.items():
            if str(tk) == bk or str(tk).lower() == bk.lower():
                breakdown[bk] = tv
                break
    return (
        breakdown,
        _float_field(target, "final_score"),
        _float_field(target, "confidence"),
    )


@router.get(
    "/{readable_id}/cohorts/{cohort_id}/member-detail",
    response_model=CohortMemberDetailResponse,
)
async def cohort_member_detail(
    readable_id: str = Path(...),
    cohort_id: UUID = Path(...),
    node_id: str = Query(..., description="Graph node_id for the member"),
    ctx: ApiContext = Depends(get_context),
) -> CohortMemberDetailResponse:
    """Deep-dive: NodeInfo for one cohort member."""
    collection = await _require_structured_collection(readable_id, ctx)
    async with get_db_context() as db:
        cohort_row = await crud.cohort.get_for_collection(
            db,
            cohort_id=cohort_id,
            collection_id=collection.id,
            ctx=ctx,
        )

    infos = await node_info(
        [node_id],
        ctx.organization.id,
        ctx,
        readable_collection_id=readable_id,
    )
    if not infos:
        raise HTTPException(status_code=404, detail="Node not found or not accessible")
    info = infos[0]

    breakdown: Dict[str, Any] = {}
    final_score: Optional[float] = None
    confidence: Optional[float] = None
    mode = getattr(cohort_row, "cohort_mode", None) or "list"
    if mode == "scoring":
        breakdown, final_score, confidence = await _scoring_member_detail_extras(
            cohort_row,
            node_id,
            ctx,
            readable_id,
        )

    return CohortMemberDetailResponse(
        node_id=str(info.get("node_id") or node_id),
        node_type=info.get("node_type"),
        name=info.get("name"),
        properties=info.get("properties") or {},
        neighbors=info.get("neighbors") or [],
        final_score=final_score,
        confidence=confidence,
        score_breakdown=breakdown,
    )
