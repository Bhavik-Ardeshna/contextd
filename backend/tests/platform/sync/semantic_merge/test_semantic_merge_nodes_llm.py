"""Scenario tests: fake people, companies, places, products — prints merge outcomes.

- 10 straightforward ``test_scenario_*`` cases
- 10 harder ``test_hard_*`` cases (multi-candidate, shadow mode, synthesis chain, etc.)

Run with ``pytest -s`` (no capture) to see stdout for each case.
"""

from __future__ import annotations

import logging
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from contextd.platform.entities._normalized import (
    LLMExtractionRef,
    NormalizedEntity,
    PersonRef,
    RelatedPersonRef,
)
from contextd.platform.sync.semantic_merge.semantic_entity_merge_service import (
    SemanticEntityMergeService,
)

ORG_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
SYNC_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")

SIMILAR_EMB = [1.0, 0.0, 0.0]
DISSIMILAR_EMB = [0.0, 1.0, 0.0]
QUERY_UNIT = [1.0, 0.0, 0.0]


def _emb_xy(cos_from_x: float) -> list[float]:
    """Unit-ish vector in the x–y plane so cosine vs QUERY_UNIT equals cos_from_x."""
    x = max(-1.0, min(1.0, cos_from_x))
    y = (max(0.0, 1.0 - x * x)) ** 0.5
    return [x, y, 0.0]

EXT_ORG = "EmailExtract:Organization"
EXT_PLACE = "EmailExtract:Place"
EXT_PRODUCT = "EmailExtract:Product"
EXT_LANDMARK = "EmailExtract:Landmark"


def _sync_ctx() -> SimpleNamespace:
    return SimpleNamespace(
        connection=SimpleNamespace(short_name="notion"),
        organization_id=ORG_ID,
        sync_id=SYNC_ID,
        collection=SimpleNamespace(vector_size=3),
        logger=logging.getLogger("semantic_merge_scenario"),
    )


def _settings(**overrides: object) -> SimpleNamespace:
    base = SimpleNamespace(
        SEMANTIC_MERGE_ENABLED=True,
        SEMANTIC_MERGE_SHADOW_MODE=False,
        SEMANTIC_MERGE_SIMILARITY_THRESHOLD=0.85,
        SEMANTIC_MERGE_TOP_K=5,
        SEMANTIC_MERGE_LLM_JUDGE_ENABLED=True,
        SEMANTIC_MERGE_LLM_SYNTHESIS_ON_CONFLICT=False,
    )

    def allow(short: str) -> bool:
        return short == "notion"

    base.is_semantic_merge_allowed_for_connector = allow
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def _profile(cid: str, emb: list[float], props: dict) -> SimpleNamespace:
    return SimpleNamespace(
        canonical_node_id=cid,
        embedding_json=emb,
        merged_properties_json=props,
    )


def _ext(
    eid: str,
    entity_type: str,
    name: str,
    description: str | None,
) -> LLMExtractionRef:
    return LLMExtractionRef(
        id=eid,
        entity_type=entity_type,
        name=name,
        edge_type="CONTAINS",
        description=description,
    )


def _print_case(
    title: str,
    *,
    prior: str,
    incoming: str,
    merged: bool,
    resolved_id: str,
    hint: str = "",
) -> None:
    outcome = "MERGED (linked to existing canonical)" if merged else "NOT MERGED (new canonical)"
    print(f"\n{'═' * 72}")
    print(f"  {title}")
    print(f"  Prior nodes / profiles: {prior}")
    print(f"  Incoming: {incoming}")
    print(f"  → {outcome}")
    print(f"  Resolved id: {resolved_id}")
    if hint:
        print(f"  ({hint})")
    print(f"{'═' * 72}")


def _wire_alias_mocks(
    ea: object,
    *,
    list_return: list,
    get_profile: AsyncMock,
) -> None:
    ea.get_canonical_by_alias = AsyncMock(return_value=None)
    ea.get_canonical_by_alias_any_type = AsyncMock(return_value=None)
    ea.list_profiles_for_entity_type = AsyncMock(return_value=list_return)
    ea.list_profiles_any_type = AsyncMock(return_value=list_return)
    ea.get_profile = get_profile

    async def gp_any(
        _db: object,
        *,
        organization_id: object,
        canonical_node_id: str,
    ) -> object | None:
        return await get_profile(
            _db,
            organization_id=organization_id,
            entity_type="__semantic_global__",
            canonical_node_id=canonical_node_id,
        )

    ea.get_profile_any_type = AsyncMock(side_effect=gp_any)
    ea.upsert_alias_mapping = AsyncMock()
    ea.upsert_canonical_profile = AsyncMock()


def _get_profile_for_stored_only(stored: SimpleNamespace) -> AsyncMock:
    """Return profile only when querying that canonical (LLM judge); else None (new slug)."""

    async def gp(
        _db: object,
        *,
        organization_id: object,
        entity_type: str,
        canonical_node_id: str,
    ) -> SimpleNamespace | None:
        if canonical_node_id == stored.canonical_node_id:
            return stored
        return None

    return AsyncMock(side_effect=gp)


@pytest.fixture
def db() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def service() -> SemanticEntityMergeService:
    return SemanticEntityMergeService()


@pytest.mark.asyncio
async def test_scenario_elon_musk_abbreviated_same_ceo(db: AsyncMock, service: SemanticEntityMergeService) -> None:
    """PersonNode: prior Elon full name; incoming abbreviated + Tesla role — LLM says same person."""
    prior = (
        'PersonNode canonical "person_elon_001" — name "Elon Musk", '
        'notes: CEO of Tesla and SpaceX'
    )
    incoming = 'Person "E. Musk" / context: "CEO of Tesla, speaking at Austin factory"'
    stored = _profile(
        "person_elon_001",
        SIMILAR_EMB,
        {"name": "Elon Musk", "description": "CEO of Tesla and SpaceX"},
    )

    async def llm(_: str) -> str:
        return '{"same_entity": true}'

    service._llm_call = llm

    async def fixed_embed(_text: str, _ctx) -> list[float]:
        return list(SIMILAR_EMB)

    service._embed = fixed_embed  # type: ignore[method-assign]

    with (
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.settings",
            _settings(),
        ),
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.entity_alias"
        ) as ea,
    ):
        _wire_alias_mocks(ea, list_return=[stored], get_profile=AsyncMock(return_value=stored))
        p = PersonRef(id="slack-99", name="E. Musk", email=None, role="other")
        out = await service._merge_person(db, ORG_ID, SYNC_ID, p, _sync_ctx())
        cid = out.id
        merged = cid == "person_elon_001"
        _print_case(
            "Person — Elon Musk vs E. Musk (CEO Tesla)",
            prior=prior,
            incoming=incoming,
            merged=merged,
            resolved_id=str(cid),
            hint="vector match + LLM same_entity true",
        )
        assert merged


@pytest.mark.asyncio
async def test_scenario_two_different_tim_cooks(db: AsyncMock, service: SemanticEntityMergeService) -> None:
    """PersonNode: same common name, LLM says different real people — no merge."""
    prior = 'PersonNode "Tim Cook" — Apple CEO, Cupertino'
    incoming = 'Person "Tim Cook" — high school basketball coach, Ohio'
    stored = _profile(
        "person_apple_tim",
        SIMILAR_EMB,
        {"name": "Tim Cook", "description": "CEO of Apple Inc."},
    )

    async def llm(_: str) -> str:
        return '{"same_entity": false}'

    service._llm_call = llm

    async def fixed_embed(_text: str, _ctx) -> list[float]:
        return list(SIMILAR_EMB)

    service._embed = fixed_embed  # type: ignore[method-assign]

    hex2 = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    fake_u = MagicMock()
    fake_u.hex = hex2

    with (
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.settings",
            _settings(),
        ),
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.entity_alias"
        ) as ea,
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.uuid.uuid4",
            return_value=fake_u,
        ),
    ):
        _wire_alias_mocks(ea, list_return=[stored], get_profile=_get_profile_for_stored_only(stored))
        p = PersonRef(
            id="local-1",
            name="Tim Cook",
            email=None,
            role="other",
            properties={"note": "basketball coach"},
        )
        out = await service._merge_person(db, ORG_ID, SYNC_ID, p, _sync_ctx())
        cid = out.id
        merged = cid == "person_apple_tim"
        _print_case(
            "Person — two different Tim Cooks",
            prior=prior,
            incoming=incoming,
            merged=merged,
            resolved_id=str(cid),
            hint="LLM rejects merge despite high vector similarity",
        )
        assert not merged
        assert cid == f"person_{hex2[:12]}"


@pytest.mark.asyncio
async def test_scenario_tesla_inc_vs_tesla_motors(db: AsyncMock, service: SemanticEntityMergeService) -> None:
    """Organization extraction: same car company, different strings — merge."""
    prior = 'Organization "Tesla, Inc." — electric vehicles, Austin HQ'
    incoming = 'Organization "Tesla Motors" — EV manufacturer, CEO Elon Musk'
    stored = _profile(
        "canonical_tesla_corp",
        SIMILAR_EMB,
        {"name": "Tesla, Inc.", "description": "Electric vehicles; energy; Austin."},
    )

    async def llm(_: str) -> str:
        return '{"same_entity": true}'

    service._llm_call = llm

    async def fixed_embed(_text: str, _ctx) -> list[float]:
        return list(SIMILAR_EMB)

    service._embed = fixed_embed  # type: ignore[method-assign]

    with (
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.settings",
            _settings(),
        ),
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.entity_alias"
        ) as ea,
    ):
        _wire_alias_mocks(ea, list_return=[stored], get_profile=AsyncMock(return_value=stored))
        ex = _ext("e1", EXT_ORG, "Tesla Motors", "EV manufacturer; CEO Elon Musk")
        out = await service._merge_llm_extraction(db, ORG_ID, SYNC_ID, ex, _sync_ctx())
        merged = out.id == "canonical_tesla_corp"
        _print_case(
            "Organization — Tesla, Inc. vs Tesla Motors",
            prior=prior,
            incoming=incoming,
            merged=merged,
            resolved_id=out.id,
            hint="vector + LLM same company",
        )
        assert merged


@pytest.mark.asyncio
async def test_scenario_amazon_retail_vs_amazon_rainforest(db: AsyncMock, service: SemanticEntityMergeService) -> None:
    """Organization: similar name strings, LLM says different entities — no merge."""
    prior = 'Organization "Amazon.com, Inc." — e-commerce and cloud (Seattle)'
    incoming = 'Organization "Amazon" — rainforest biome, South America conservation NGO'
    stored = _profile(
        "canonical_amazon_com",
        SIMILAR_EMB,
        {"name": "Amazon.com, Inc.", "description": "E-commerce AWS Seattle"},
    )

    async def llm(_: str) -> str:
        return '{"same_entity": false}'

    service._llm_call = llm

    async def fixed_embed(_text: str, _ctx) -> list[float]:
        return list(SIMILAR_EMB)

    service._embed = fixed_embed  # type: ignore[method-assign]

    with (
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.settings",
            _settings(),
        ),
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.entity_alias"
        ) as ea,
    ):
        _wire_alias_mocks(ea, list_return=[stored], get_profile=_get_profile_for_stored_only(stored))
        ex = _ext(
            "e-amz-rain",
            EXT_ORG,
            "Amazon",
            "Rainforest conservation nonprofit in Brazil",
        )
        out = await service._merge_llm_extraction(db, ORG_ID, SYNC_ID, ex, _sync_ctx())
        merged = out.id == "canonical_amazon_com"
        _print_case(
            "Organization — Amazon.com vs Amazon rainforest NGO",
            prior=prior,
            incoming=incoming,
            merged=merged,
            resolved_id=out.id,
            hint="LLM distinguishes company from geographic/NGO sense",
        )
        assert not merged
        assert out.id.startswith("emailextract_organization_")


@pytest.mark.asyncio
async def test_scenario_paris_france_vs_paris_france_alias(db: AsyncMock, service: SemanticEntityMergeService) -> None:
    """Place: Paris FR vs Île-de-France capital wording — merge."""
    prior = 'Place canonical "place_paris_fr" — "Paris", country France, EU capital'
    incoming = 'Place "Paris, France" — city of lights; Seine; Louvre'
    stored = _profile(
        "place_paris_fr",
        SIMILAR_EMB,
        {"name": "Paris", "description": "Capital of France"},
    )

    async def llm(_: str) -> str:
        return '{"same_entity": true}'

    service._llm_call = llm

    async def fixed_embed(_text: str, _ctx) -> list[float]:
        return list(SIMILAR_EMB)

    service._embed = fixed_embed  # type: ignore[method-assign]

    with (
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.settings",
            _settings(),
        ),
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.entity_alias"
        ) as ea,
    ):
        _wire_alias_mocks(ea, list_return=[stored], get_profile=AsyncMock(return_value=stored))
        ex = _ext("e-paris", EXT_PLACE, "Paris, France", "Seine river; museums; EU hub")
        out = await service._merge_llm_extraction(db, ORG_ID, SYNC_ID, ex, _sync_ctx())
        merged = out.id == "place_paris_fr"
        _print_case(
            "Place — Paris (canonical) vs Paris, France phrasing",
            prior=prior,
            incoming=incoming,
            merged=merged,
            resolved_id=out.id,
            hint="same city, LLM confirms",
        )
        assert merged


@pytest.mark.asyncio
async def test_scenario_paris_texas_vs_paris_france_embedding_split(db: AsyncMock, service: SemanticEntityMergeService) -> None:
    """Place: Paris Texas vs Paris France — embeddings orthogonal, no vector merge."""
    prior = 'Place "Paris, France" (EU)'
    incoming = 'Place "Paris, Texas" — Lamar County seat, USA'
    stored = _profile(
        "place_paris_france",
        DISSIMILAR_EMB,
        {"name": "Paris", "description": "France capital"},
    )

    async def llm_forbidden(_: str) -> str:
        raise AssertionError("LLM must not run when similarity is below threshold")

    service._llm_call = llm_forbidden

    async def query_embed(_text: str, _ctx) -> list[float]:
        return list(SIMILAR_EMB)

    service._embed = query_embed  # type: ignore[method-assign]

    with (
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.settings",
            _settings(),
        ),
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.entity_alias"
        ) as ea,
    ):
        _wire_alias_mocks(ea, list_return=[stored], get_profile=AsyncMock(return_value=None))
        ex = _ext("e-paris-tx", EXT_PLACE, "Paris, Texas", "Small city in Texas, USA")
        out = await service._merge_llm_extraction(db, ORG_ID, SYNC_ID, ex, _sync_ctx())
        merged = out.id == "place_paris_france"
        _print_case(
            "Place — Paris France vs Paris Texas (dissimilar vectors)",
            prior=prior,
            incoming=incoming,
            merged=merged,
            resolved_id=out.id,
            hint="cosine below threshold → separate canonical",
        )
        assert not merged


@pytest.mark.asyncio
async def test_scenario_starbucks_alias_name_hit(db: AsyncMock, service: SemanticEntityMergeService) -> None:
    """Organization: name alias already in DB — merge without vector/LLM judge."""
    prior = (
        'Alias row: name_key for "Blue Bottle Coffee" → canonical "org_blue_bottle"'
    )
    incoming = 'New doc mentions organization "Blue Bottle Coffee" again'

    async def forbid_llm(_: str) -> str:
        raise AssertionError("LLM judge should not run on pure alias hit")

    service._llm_call = forbid_llm

    async def fixed_embed(_text: str, _ctx) -> list[float]:
        return list(SIMILAR_EMB)

    service._embed = fixed_embed  # type: ignore[method-assign]

    with (
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.settings",
            _settings(),
        ),
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.entity_alias"
        ) as ea,
    ):
        ea.get_canonical_by_alias = AsyncMock(return_value="org_blue_bottle")
        ea.get_canonical_by_alias_any_type = AsyncMock(return_value="org_blue_bottle")
        ea.list_profiles_for_entity_type = AsyncMock(
            side_effect=AssertionError("list_profiles should not run after alias hit")
        )
        ea.list_profiles_any_type = AsyncMock(
            side_effect=AssertionError("list_profiles_any_type should not run after alias hit")
        )
        ea.get_profile = AsyncMock(return_value=None)
        ea.get_profile_any_type = AsyncMock(return_value=None)
        ea.upsert_alias_mapping = AsyncMock()
        ea.upsert_canonical_profile = AsyncMock()
        ex = _ext("e-bb", EXT_ORG, "Blue Bottle Coffee", "Third-wave coffee roaster")
        out = await service._merge_llm_extraction(db, ORG_ID, SYNC_ID, ex, _sync_ctx())
        merged = out.id == "org_blue_bottle"
        _print_case(
            "Organization — alias hit (Blue Bottle Coffee)",
            prior=prior,
            incoming=incoming,
            merged=merged,
            resolved_id=out.id,
            hint="get_canonical_by_alias short-circuits vector+LLM",
        )
        assert merged


@pytest.mark.asyncio
async def test_scenario_iphone_models_product_line(db: AsyncMock, service: SemanticEntityMergeService) -> None:
    """Product: iPhone 15 Pro vs stored iPhone 15 Pro Max — LLM says same product line merge."""
    prior = 'Product "Apple iPhone 15 Pro Max" — 2023 flagship smartphone'
    incoming = 'Product "iPhone 15 Pro" — titanium, Action button, A17 Pro'
    stored = _profile(
        "product_iphone_15_pro_max",
        SIMILAR_EMB,
        {"name": "iPhone 15 Pro Max", "description": "Apple smartphone 2023"},
    )

    async def llm(_: str) -> str:
        return '{"same_entity": true}'

    service._llm_call = llm

    async def fixed_embed(_text: str, _ctx) -> list[float]:
        return list(SIMILAR_EMB)

    service._embed = fixed_embed  # type: ignore[method-assign]

    with (
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.settings",
            _settings(),
        ),
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.entity_alias"
        ) as ea,
    ):
        _wire_alias_mocks(ea, list_return=[stored], get_profile=AsyncMock(return_value=stored))
        ex = _ext("e-iph", EXT_PRODUCT, "iPhone 15 Pro", "Titanium; Pro camera system")
        out = await service._merge_llm_extraction(db, ORG_ID, SYNC_ID, ex, _sync_ctx())
        merged = out.id == "product_iphone_15_pro_max"
        _print_case(
            "Product — iPhone 15 Pro vs iPhone 15 Pro Max (same line)",
            prior=prior,
            incoming=incoming,
            merged=merged,
            resolved_id=out.id,
            hint="LLM treats as same product family anchor",
        )
        assert merged


@pytest.mark.asyncio
async def test_scenario_eiffel_tower_french_english(db: AsyncMock, service: SemanticEntityMergeService) -> None:
    """Landmark: Eiffel Tower vs Tour Eiffel — merge."""
    prior = 'Landmark "Eiffel Tower" — iron lattice tower, Champ de Mars, Paris'
    incoming = 'Landmark "Tour Eiffel" — monument construit pour Exposition 1889'
    stored = _profile(
        "landmark_eiffel_tower",
        SIMILAR_EMB,
        {"name": "Eiffel Tower", "description": "Paris landmark Gustave Eiffel"},
    )

    async def llm(_: str) -> str:
        return '{"same_entity": true}'

    service._llm_call = llm

    async def fixed_embed(_text: str, _ctx) -> list[float]:
        return list(SIMILAR_EMB)

    service._embed = fixed_embed  # type: ignore[method-assign]

    with (
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.settings",
            _settings(),
        ),
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.entity_alias"
        ) as ea,
    ):
        _wire_alias_mocks(ea, list_return=[stored], get_profile=AsyncMock(return_value=stored))
        ex = _ext("e-tour", EXT_LANDMARK, "Tour Eiffel", "Monument emblématique de Paris")
        out = await service._merge_llm_extraction(db, ORG_ID, SYNC_ID, ex, _sync_ctx())
        merged = out.id == "landmark_eiffel_tower"
        _print_case(
            "Landmark — Eiffel Tower vs Tour Eiffel",
            prior=prior,
            incoming=incoming,
            merged=merged,
            resolved_id=out.id,
            hint="English/French names same landmark",
        )
        assert merged


@pytest.mark.asyncio
async def test_scenario_spacex_two_step_ingest_merge(db: AsyncMock, service: SemanticEntityMergeService) -> None:
    """Organization: first ingest creates profile; second legal name — merges into first canonical."""
    prior_round1 = "(empty profile store — first document)"
    incoming1 = 'Organization "SpaceX" — rockets, Hawthorne CA'
    incoming2 = 'Organization "Space Exploration Technologies Corp." — Starship, Starlink'

    profile_store: list[SimpleNamespace] = []

    async def llm(_: str) -> str:
        return '{"same_entity": true}'

    service._llm_call = llm

    async def list_profiles(*_a, **_kw):
        return list(profile_store)

    async def upsert_profile(
        *_a,
        canonical_node_id: str,
        embedding_json=None,
        merged_properties_json=None,
        **_kw,
    ):
        profile_store.append(
            _profile(
                canonical_node_id,
                list(embedding_json or SIMILAR_EMB),
                dict(merged_properties_json or {}),
            )
        )

    async def fixed_embed(_text: str, _ctx) -> list[float]:
        return list(SIMILAR_EMB)

    service._embed = fixed_embed  # type: ignore[method-assign]

    with (
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.settings",
            _settings(),
        ),
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.entity_alias"
        ) as ea,
    ):
        ea.get_canonical_by_alias = AsyncMock(return_value=None)
        ea.get_canonical_by_alias_any_type = AsyncMock(return_value=None)
        ea.list_profiles_for_entity_type = AsyncMock(side_effect=list_profiles)
        ea.list_profiles_any_type = AsyncMock(side_effect=list_profiles)

        async def gp_spacex(
            _db: object,
            *,
            organization_id: object,
            entity_type: str,
            canonical_node_id: str,
        ) -> SimpleNamespace | None:
            return profile_store[0] if profile_store else None

        ea.get_profile = AsyncMock(side_effect=gp_spacex)

        async def gp_any_spacex(
            _db: object,
            *,
            organization_id: object,
            canonical_node_id: str,
        ) -> SimpleNamespace | None:
            return profile_store[0] if profile_store else None

        ea.get_profile_any_type = AsyncMock(side_effect=gp_any_spacex)
        ea.upsert_alias_mapping = AsyncMock()
        ea.upsert_canonical_profile = AsyncMock(side_effect=upsert_profile)

        first = await service._merge_llm_extraction(
            db, ORG_ID, SYNC_ID, _ext("d1", EXT_ORG, "SpaceX", "Hawthorne rockets"), _sync_ctx()
        )
        second = await service._merge_llm_extraction(
            db,
            ORG_ID,
            SYNC_ID,
            _ext(
                "d2",
                EXT_ORG,
                "Space Exploration Technologies Corp.",
                "Starship; Starlink constellation",
            ),
            _sync_ctx(),
        )
        merged = second.id == first.id
        print(f"\n{'═' * 72}")
        print("  Organization — two-step SpaceX ingest (whole flow)")
        print(f"  Round 1 prior: {prior_round1}")
        print(f"  Round 1 incoming: {incoming1}")
        print(f"  → First canonical: {first.id!r}")
        print(f"  Round 2 incoming: {incoming2}")
        print(f"  → Second canonical: {second.id!r}")
        print(
            f"  Outcome: {'MERGED (second → first)' if merged else 'NOT MERGED (unexpected split)'}"
        )
        print(f"{'═' * 72}")
        assert merged


# --- Harder / non-obvious scenarios ---


def _profiles_by_id_map(*profiles: SimpleNamespace) -> AsyncMock:
    by_id = {p.canonical_node_id: p for p in profiles}

    async def gp(
        _db: object,
        *,
        organization_id: object,
        entity_type: str,
        canonical_node_id: str,
    ) -> SimpleNamespace | None:
        return by_id.get(canonical_node_id)

    return AsyncMock(side_effect=gp)


@pytest.mark.asyncio
async def test_hard_multi_candidate_picks_highest_cosine_not_first_in_list(
    db: AsyncMock, service: SemanticEntityMergeService
) -> None:
    """Three profiles ≥ threshold but unsorted; resolver must pick best similarity, not list order."""
    prior = (
        "Three Organization profiles (order shuffled): "
        "0.87, 0.99, 0.91 cosine vs query — winner must be 0.99"
    )
    incoming = 'Incoming "Acme Global HQ" (ambiguous which Acme node)'
    p_lo = _profile("org_acme_087", _emb_xy(0.87), {"name": "Acme Regional", "description": ""})
    p_hi = _profile("org_acme_099", _emb_xy(0.99), {"name": "Acme Global", "description": "HQ"})
    p_mid = _profile("org_acme_091", _emb_xy(0.91), {"name": "Acme Labs", "description": ""})
    shuffled = [p_lo, p_hi, p_mid]

    prompts: list[str] = []

    async def llm(p: str) -> str:
        prompts.append(p)
        return '{"same_entity": true}'

    service._llm_call = llm

    async def fixed_embed(_text: str, _ctx) -> list[float]:
        return list(QUERY_UNIT)

    service._embed = fixed_embed  # type: ignore[method-assign]

    with (
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.settings",
            _settings(),
        ),
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.entity_alias"
        ) as ea,
    ):
        _wire_alias_mocks(
            ea, list_return=shuffled, get_profile=_profiles_by_id_map(p_lo, p_hi, p_mid)
        )
        out = await service._merge_llm_extraction(
            db, ORG_ID, SYNC_ID, _ext("h1", EXT_ORG, "Acme Global HQ", "Planning office"), _sync_ctx()
        )
        merged = out.id == "org_acme_099"
        assert "Acme Global" in prompts[0] or "B name" in prompts[0]
        _print_case(
            "HARD: multi-candidate vector shortlist — highest cosine wins",
            prior=prior,
            incoming=incoming,
            merged=merged,
            resolved_id=out.id,
            hint="sorted by similarity, not DB row order",
        )
        assert merged


@pytest.mark.asyncio
async def test_hard_llm_response_json_inside_markdown_fence(db: AsyncMock, service: SemanticEntityMergeService) -> None:
    """Parser extracts inner {...}; prose + fences should not break merge."""
    prior = "One org profile; model returns chatty markdown-wrapped JSON"
    incoming = 'Incoming org "Contoso EU"'
    stored = _profile("canonical_contoso", SIMILAR_EMB, {"name": "Contoso Ltd", "description": "B2B"})

    async def llm(_: str) -> str:
        return 'Here you go:\n```json\n{"same_entity": true, "note": "ignore"}\n```'

    service._llm_call = llm

    async def fixed_embed(_text: str, _ctx) -> list[float]:
        return list(SIMILAR_EMB)

    service._embed = fixed_embed  # type: ignore[method-assign]

    with (
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.settings",
            _settings(),
        ),
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.entity_alias"
        ) as ea,
    ):
        _wire_alias_mocks(
            ea, list_return=[stored], get_profile=_profiles_by_id_map(stored)
        )
        out = await service._merge_llm_extraction(
            db, ORG_ID, SYNC_ID, _ext("h2", EXT_ORG, "Contoso EU", "Sales office"), _sync_ctx()
        )
        merged = out.id == "canonical_contoso"
        _print_case(
            "HARD: LLM wraps JSON in markdown — still merges",
            prior=prior,
            incoming=incoming,
            merged=merged,
            resolved_id=out.id,
            hint="_llm_same_entity substring JSON parse",
        )
        assert merged


@pytest.mark.asyncio
async def test_hard_shadow_mode_never_reuses_vector_canonical(db: AsyncMock, service: SemanticEntityMergeService) -> None:
    """Shadow mode skips vector resolution and DB writes — identical embedding would merge without shadow."""
    prior = (
        'Profile "phantom_canonical" with perfect cosine match — '
        "shadow=True must still mint a fresh slug and skip alias upserts"
    )
    incoming = 'Org "GhostCo" (would match phantom in live mode)'
    stored = _profile("phantom_canonical", SIMILAR_EMB, {"name": "GhostCo", "description": "same"})

    service._llm_call = AsyncMock(side_effect=AssertionError("no LLM judge in shadow vector skip"))

    async def fixed_embed(_text: str, _ctx) -> list[float]:
        return list(SIMILAR_EMB)

    service._embed = fixed_embed  # type: ignore[method-assign]

    upserts = []

    with (
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.settings",
            _settings(SEMANTIC_MERGE_SHADOW_MODE=True),
        ),
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.entity_alias"
        ) as ea,
    ):
        _wire_alias_mocks(ea, list_return=[stored], get_profile=AsyncMock(return_value=None))

        async def capture_upsert(*a, **kw):
            upserts.append(kw)
            return MagicMock()

        ea.upsert_alias_mapping = AsyncMock(side_effect=capture_upsert)
        ea.upsert_canonical_profile = AsyncMock(side_effect=capture_upsert)

        out = await service._merge_llm_extraction(
            db, ORG_ID, SYNC_ID, _ext("h3", EXT_ORG, "GhostCo", "Shadow ingest"), _sync_ctx()
        )
        merged = out.id == "phantom_canonical"
        _print_case(
            "HARD: shadow mode — vector hit ignored, no persistence",
            prior=prior,
            incoming=incoming,
            merged=merged,
            resolved_id=out.id,
            hint=f"upsert calls recorded: {len(upserts)} (expect 0)",
        )
        assert not merged
        assert out.id.startswith("emailextract_organization_")
        assert len(upserts) == 0


@pytest.mark.asyncio
async def test_hard_null_embedding_aborts_vector_resolution(db: AsyncMock, service: SemanticEntityMergeService) -> None:
    """No query vector → never scores candidates (even if profiles exist)."""
    prior = "Rich profile store; embedder returns None (e.g. empty / failed embed)"
    incoming = 'Org "NullVec Corp"'
    stored = _profile("would_match", SIMILAR_EMB, {"name": "NullVec Corp", "description": ""})

    service._llm_call = AsyncMock(side_effect=AssertionError("LLM must not run without vector path"))

    async def no_emb(_text: str, _ctx) -> list[float] | None:
        return None

    service._embed = no_emb  # type: ignore[method-assign]

    with (
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.settings",
            _settings(),
        ),
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.entity_alias"
        ) as ea,
    ):
        _wire_alias_mocks(ea, list_return=[stored], get_profile=AsyncMock(return_value=None))
        out = await service._merge_llm_extraction(
            db, ORG_ID, SYNC_ID, _ext("h4", EXT_ORG, "NullVec Corp", "x"), _sync_ctx()
        )
        merged = out.id == "would_match"
        _print_case(
            "HARD: missing query embedding — no vector merge",
            prior=prior,
            incoming=incoming,
            merged=merged,
            resolved_id=out.id,
            hint="no_vector_candidates",
        )
        assert not merged


@pytest.mark.asyncio
async def test_hard_profiles_with_missing_embeddings_skipped(db: AsyncMock, service: SemanticEntityMergeService) -> None:
    """Several rows: null / invalid embedding_json skipped until first valid high-sim profile."""
    prior = (
        "Profile A: embedding_json=None; B: invalid type; C: valid high match — "
        "only C participates in scoring"
    )
    incoming = 'Place "Lake Tahoe South Shore"'
    bad_none = _profile("bad_none", [], {})  # list empty triggers cosine 0 path - actually emb check: `if not emb`
    # Service checks `if not emb` - [] is falsy, skipped
    bad_wrong = SimpleNamespace(
        canonical_node_id="bad_wrong",
        embedding_json="not-a-list",
        merged_properties_json={},
    )
    good = _profile(
        "place_tahoe",
        SIMILAR_EMB,
        {"name": "Lake Tahoe", "description": "Alpine lake CA/NV"},
    )

    async def llm(_: str) -> str:
        return '{"same_entity": true}'

    service._llm_call = llm

    async def fixed_embed(_text: str, _ctx) -> list[float]:
        return list(SIMILAR_EMB)

    service._embed = fixed_embed  # type: ignore[method-assign]

    with (
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.settings",
            _settings(),
        ),
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.entity_alias"
        ) as ea,
    ):
        _wire_alias_mocks(
            ea,
            list_return=[bad_none, bad_wrong, good],
            get_profile=_profiles_by_id_map(good),
        )
        out = await service._merge_llm_extraction(
            db,
            ORG_ID,
            SYNC_ID,
            _ext("h5", EXT_PLACE, "Lake Tahoe South Shore", "ski towns"),
            _sync_ctx(),
        )
        merged = out.id == "place_tahoe"
        _print_case(
            "HARD: corrupt / empty embeddings filtered — still find winner",
            prior=prior,
            incoming=incoming,
            merged=merged,
            resolved_id=out.id,
            hint="isinstance(emb, list) guard",
        )
        assert merged


@pytest.mark.asyncio
async def test_hard_subsidiary_brand_llm_links_to_parent_retailer(db: AsyncMock, service: SemanticEntityMergeService) -> None:
    """Incoming banner name vs parent-company profile — requires LLM, not string equality."""
    prior = (
        'Profile canonical "mega_retail" name "MegaRetail Holdings" '
        'desc mentions Whole Foods acquisition'
    )
    incoming = 'Org name "Whole Foods Market" — grocery banner only in text'
    stored = _profile(
        "mega_retail",
        SIMILAR_EMB,
        {
            "name": "MegaRetail Holdings",
            "description": "Parent of Whole Foods Market since acquisition",
        },
    )

    async def llm(_: str) -> str:
        return '{"same_entity": true}'

    service._llm_call = llm

    async def fixed_embed(_text: str, _ctx) -> list[float]:
        return list(SIMILAR_EMB)

    service._embed = fixed_embed  # type: ignore[method-assign]

    with (
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.settings",
            _settings(),
        ),
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.entity_alias"
        ) as ea,
    ):
        _wire_alias_mocks(
            ea, list_return=[stored], get_profile=_profiles_by_id_map(stored)
        )
        out = await service._merge_llm_extraction(
            db,
            ORG_ID,
            SYNC_ID,
            _ext("h6", EXT_ORG, "Whole Foods Market", "Organic grocery chain"),
            _sync_ctx(),
        )
        merged = out.id == "mega_retail"
        _print_case(
            "HARD: subsidiary brand vs parent org profile",
            prior=prior,
            incoming=incoming,
            merged=merged,
            resolved_id=out.id,
            hint="LLM disambiguation beyond surface name match",
        )
        assert merged


@pytest.mark.asyncio
async def test_hard_description_conflict_triggers_second_llm_synthesis(
    db: AsyncMock, service: SemanticEntityMergeService
) -> None:
    """After vector+LLM merge, conflicting descriptions invoke synthesize_summary_if_needed (2nd LLM)."""
    long_base = "on-prem LLM appliance product line for enterprise customers worldwide"
    prior = f'Org "Nebula AI" profile description (long): "{long_base[:40]}..."'
    incoming = 'Extraction repeats shorter tagline in properties + description field'
    stored = _profile(
        "org_nebula",
        SIMILAR_EMB,
        {"name": "Nebula AI", "description": long_base},
    )
    calls: list[str] = []

    async def llm(p: str) -> str:
        calls.append(p)
        if "same real-world entity" in p:
            return '{"same_entity": true}'
        return "Nebula AI: hybrid on-prem appliances and hosted embedding APIs."

    service._llm_call = llm

    async def fixed_embed(_text: str, _ctx) -> list[float]:
        return list(SIMILAR_EMB)

    service._embed = fixed_embed  # type: ignore[method-assign]

    merge_st = _settings(SEMANTIC_MERGE_LLM_SYNTHESIS_ON_CONFLICT=True)
    synth_core = SimpleNamespace(SEMANTIC_MERGE_LLM_SYNTHESIS_ON_CONFLICT=True)

    ex = LLMExtractionRef(
        id="h7",
        entity_type=EXT_ORG,
        name="Nebula AI",
        edge_type="CONTAINS",
        description="cloud API for embeddings",
        properties={"description": "cloud API for embeddings"},
    )

    with (
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.settings",
            merge_st,
        ),
        patch("contextd.core.config.settings", synth_core),
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.entity_alias"
        ) as ea,
    ):
        _wire_alias_mocks(
            ea, list_return=[stored], get_profile=_profiles_by_id_map(stored)
        )
        out = await service._merge_llm_extraction(db, ORG_ID, SYNC_ID, ex, _sync_ctx())
        merged = out.id == "org_nebula"
        synthesized = len(calls) >= 2 and "Merge the following two descriptions" in calls[1]
        _print_case(
            "HARD: post-merge description conflict → synthesis LLM",
            prior=prior,
            incoming=incoming,
            merged=merged,
            resolved_id=out.id,
            hint=f"LLM calls={len(calls)} judge+synthesis={synthesized}",
        )
        assert merged
        assert synthesized
        assert "hybrid" in (out.description or "").lower()


@pytest.mark.asyncio
async def test_hard_unicode_city_munich_ascii_equivalent(db: AsyncMock, service: SemanticEntityMergeService) -> None:
    """German spelling vs ASCII transliteration — LLM must affirm same municipality."""
    prior = 'Place profile "city_muc" name "München" (German)'
    incoming = 'Place "Munich" English exonym; same metro region'
    stored = _profile(
        "city_muc",
        SIMILAR_EMB,
        {"name": "München", "description": "Capital of Bavaria"},
    )

    async def llm(_: str) -> str:
        return '{"same_entity": true}'

    service._llm_call = llm

    async def fixed_embed(_text: str, _ctx) -> list[float]:
        return list(SIMILAR_EMB)

    service._embed = fixed_embed  # type: ignore[method-assign]

    with (
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.settings",
            _settings(),
        ),
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.entity_alias"
        ) as ea,
    ):
        _wire_alias_mocks(
            ea, list_return=[stored], get_profile=_profiles_by_id_map(stored)
        )
        out = await service._merge_llm_extraction(
            db, ORG_ID, SYNC_ID, _ext("h8", EXT_PLACE, "Munich", "Bavaria Germany"), _sync_ctx()
        )
        merged = out.id == "city_muc"
        _print_case(
            "HARD: Unicode München vs ASCII Munich",
            prior=prior,
            incoming=incoming,
            merged=merged,
            resolved_id=out.id,
            hint="cross-script exonyms",
        )
        assert merged


@pytest.mark.asyncio
async def test_hard_raised_similarity_threshold_blocks_near_miss(db: AsyncMock, service: SemanticEntityMergeService) -> None:
    """Threshold 0.92 rejects 0.88 cosine — no LLM call (below_threshold)."""
    prior = "Profile vector cosine 0.88 vs query; SEMANTIC_MERGE_SIMILARITY_THRESHOLD=0.92"
    incoming = 'Org "NearMiss Labs"'
    stored = _profile("almost", _emb_xy(0.88), {"name": "NearMiss Labs", "description": ""})

    service._llm_call = AsyncMock(side_effect=AssertionError("LLM must not run below threshold"))

    async def fixed_embed(_text: str, _ctx) -> list[float]:
        return list(QUERY_UNIT)

    service._embed = fixed_embed  # type: ignore[method-assign]

    with (
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.settings",
            _settings(SEMANTIC_MERGE_SIMILARITY_THRESHOLD=0.92),
        ),
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.entity_alias"
        ) as ea,
    ):
        _wire_alias_mocks(ea, list_return=[stored], get_profile=AsyncMock(return_value=None))
        out = await service._merge_llm_extraction(
            db, ORG_ID, SYNC_ID, _ext("h9", EXT_ORG, "NearMiss Labs", "R&D"), _sync_ctx()
        )
        merged = out.id == "almost"
        _print_case(
            "HARD: stricter threshold — near-miss cosine rejected",
            prior=prior,
            incoming=incoming,
            merged=merged,
            resolved_id=out.id,
            hint="0.88 < 0.92 → below_threshold",
        )
        assert not merged


@pytest.mark.asyncio
async def test_hard_full_normalized_entity_person_extraction_and_related_person(
    db: AsyncMock, service: SemanticEntityMergeService
) -> None:
    """Single apply_to_normalized_entities mutates people, llm_extractions, and nested related_persons."""
    prior = (
        "Empty vector catalog → person canonical from email; new org slug; "
        "related_person resolves through same _merge_person hop"
    )
    expected_person = "person_sam@example.com"

    async def llm(_: str) -> str:
        return '{"same_entity": true}'

    service._llm_call = llm

    async def fixed_embed(_text: str, _ctx) -> list[float]:
        return list(SIMILAR_EMB)

    service._embed = fixed_embed  # type: ignore[method-assign]

    ext = LLMExtractionRef(
        id="ext-1",
        entity_type=EXT_ORG,
        name="Project Aurora",
        edge_type="MENTIONS",
        description="Cross-functional initiative",
        related_persons=[
            RelatedPersonRef(email="sam@example.com", name="Sam Rivera", role="OWNER")
        ],
    )
    entity = NormalizedEntity(
        entity_id="doc-900",
        entity_type="NotionPageEntity",
        source_type="notion",
        name="Strategy memo",
        people=[PersonRef(id="u1", name="Sam Rivera", email="sam@example.com", role="owner")],
        llm_extractions=[ext],
    )

    with (
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.settings",
            _settings(),
        ),
        patch(
            "contextd.platform.sync.semantic_merge.semantic_entity_merge_service.entity_alias"
        ) as ea,
    ):
        ea.get_canonical_by_alias = AsyncMock(return_value=None)
        ea.get_canonical_by_alias_any_type = AsyncMock(return_value=None)
        ea.list_profiles_for_entity_type = AsyncMock(return_value=[])
        ea.list_profiles_any_type = AsyncMock(return_value=[])
        ea.get_profile = AsyncMock(return_value=None)
        ea.get_profile_any_type = AsyncMock(return_value=None)
        ea.upsert_alias_mapping = AsyncMock()
        ea.upsert_canonical_profile = AsyncMock()

        out_ent = await service.apply_to_normalized_entities(db, entity, _sync_ctx())
        person_cid = out_ent.people[0].id
        ext_out = out_ent.llm_extractions[0]
        rp_cid = ext_out.related_persons[0].canonical_node_id
        person_ok = person_cid == expected_person
        ext_slug = ext_out.id.startswith("emailextract_organization_")
        related_ok = rp_cid == person_cid
        print(f"\n{'═' * 72}")
        print("  HARD: full apply — person + extraction + related_person")
        print(f"  Person canonical: {person_cid!r} (expected email-based id)")
        print(f"  Extraction canonical: {ext_out.id!r}")
        print(f"  Related person canonical_node_id: {rp_cid!r}")
        print(f"  Related matches person: {related_ok}")
        print(f"{'═' * 72}")
        assert person_ok
        assert ext_slug
        assert related_ok
