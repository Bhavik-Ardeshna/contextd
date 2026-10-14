"""Semantic merge for unstructured sync: alias + vector match + optional LLM judge.

**LLM person extractions → PersonNode**

``EmailExtract:Person`` (and ``*:Person`` extractions) are **folded** into
``normalized.people`` as ``PersonRef`` with role ``mentioned`` before graph events run.
They no longer create separate ``EmailExtract:Person`` graph nodes—only ``PersonNode``
is emitted, with message↔person edges (e.g. ``MENTIONS_PERSON`` for Gmail).

**Merge behavior**

When ``SEMANTIC_MERGE_ENABLED`` is on, **PersonNode** semantic merge (alias DB + vector +
optional LLM) runs for **every** connector, including structured DB sources, so LLM-extracted
people share ``node_id``/profiles with Gmail and other sources. Global merge of the **source
entity** (non-person) into the shared pool still runs only for **unstructured** connectors
(see ``is_semantic_merge_allowed_for_connector``).

When a person matches an existing profile (alias or vector), the **same** graph
``node_id`` is reused (``person_<email>`` for email-known identities). Properties are
deterministically merged; optional LLM merges conflicting string descriptions.

**Ambiguities and failure modes**

- **No email on extraction:** Matching relies on name + vectors; higher false merge risk.
- **Vector similarity:** Wrong candidate if embeddings collide (similar names, thin text).
- **LLM judge / synthesis:** Optional; API or prompt failures fall back to deterministic text.
- **Same name, different people:** Without email, deduplication is ambiguous.
- **Multi-tenant:** Aliases are scoped by ``organization_id``; collection is not always
  part of the merge key—cross-collection duplicate risk if the same person appears twice.

Legacy field ``semantic_canonical_node_id`` on ``PersonRef`` is no longer set; the
resolved graph id is carried on ``PersonRef.id`` after merge.

LightRAG-style merge also runs on the source normalized entity and non-person
``llm_extractions`` into the global semantic pool.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from contextd.core.config import settings
from contextd.crud.crud_entity_alias import entity_alias
from contextd.platform.contexts.sync import SyncContext
from contextd.platform.entities._normalized import (
    LLMExtractionRef,
    NormalizedEntity,
    PersonRef,
    PersonRole,
    RelatedPersonRef,
)
from contextd.platform.sync.semantic_merge.alias_keys import (
    email_alias_key,
    extraction_text_for_embedding,
    name_alias_key,
)
from contextd.platform.sync.semantic_merge.normalize_identity import normalize_email
from contextd.platform.sync.semantic_merge.property_synthesis import (
    embedding_text_hash,
    merge_dicts_deterministic,
    synthesize_summary_if_needed,
)
from contextd.platform.sync.semantic_merge.vector_similarity import cosine_similarity

logger = logging.getLogger(__name__)

PERSON_NODE_ENTITY_TYPE = "PersonNode"
GLOBAL_MERGE_ENTITY_TYPE = "__semantic_global__"


class SemanticEntityMergeService:
    """Applies semantic merge to normalized entities."""

    def __init__(self) -> None:
        self._llm_call: Optional[Callable[[str], Any]] = None

    @staticmethod
    def _log_merge_resolution(
        sync_context: SyncContext,
        *,
        kind: str,
        label: str,
        canonical_node_id: str,
        match_method: str,
    ) -> None:
        """Log one resolution. INFO when tied to an existing canonical; DEBUG for brand-new IDs."""
        safe_label = (label or "?")[:200]
        msg = (
            f"[SemanticMerge] {kind} {safe_label!r} -> canonical={canonical_node_id} "
            f"method={match_method}"
        )
        if match_method in ("new_canonical", "new_id"):
            sync_context.logger.debug(msg)
        else:
            sync_context.logger.info(msg)

    @staticmethod
    def fold_llm_person_extractions_into_people(
        normalized: NormalizedEntity,
    ) -> NormalizedEntity:
        """Move LLM ``*:Person`` extractions into ``people``; drop separate extraction nodes.

        Safe to call multiple times (no-op if no person-shaped extractions remain).
        """
        if not normalized.llm_extractions:
            merged_people = SemanticEntityMergeService._merge_people_list_after_fold(
                list(normalized.people), []
            )
            return normalized.model_copy(update={"people": merged_people})

        kept: List[LLMExtractionRef] = []
        extra: List[PersonRef] = []

        for ext in normalized.llm_extractions:
            if not SemanticEntityMergeService._is_llm_extracted_person(ext):
                kept.append(ext)
                continue

            email = SemanticEntityMergeService._email_from_person_extraction(ext)
            props = {
                k: v
                for k, v in (ext.properties or {}).items()
                if k not in ("email", "related_to", "related_persons")
            }
            if ext.description:
                props.setdefault("description", ext.description)
            props["llm_person_extraction"] = True
            props["extraction_confidence"] = ext.confidence
            if ext.extraction_model:
                props["extraction_model"] = ext.extraction_model

            if email:
                ne = normalize_email(email) or email.lower().strip()
                props.setdefault("email", ne)
                extra.append(
                    PersonRef(
                        id=ne,
                        name=ext.name,
                        email=ne,
                        role=PersonRole.MENTIONED,
                        properties=props,
                    )
                )
            else:
                safe = (ext.name or "unknown").lower().strip().replace(" ", "_")[:80]
                extra.append(
                    PersonRef(
                        id=f"mentioned_name_{safe}_{uuid.uuid4().hex[:8]}",
                        name=ext.name,
                        email=None,
                        role=PersonRole.MENTIONED,
                        properties=props,
                    )
                )

        merged_people = SemanticEntityMergeService._merge_people_list_after_fold(
            list(normalized.people), extra
        )
        return normalized.model_copy(
            update={"people": merged_people, "llm_extractions": kept}
        )

    @staticmethod
    def _is_llm_extracted_person(ext: LLMExtractionRef) -> bool:
        et = (ext.entity_type or "").strip()
        if not et:
            return False
        # Accept bare "Person" (LLM extractor emits this when llm_config.base_node_type
        # is unset) as well as prefixed forms like "EmailExtract:Person".
        tail = et.split(":")[-1].lower()
        return tail == "person"

    @staticmethod
    def _email_from_person_extraction(ext: LLMExtractionRef) -> Optional[str]:
        p = ext.properties or {}
        raw = p.get("email") or ext.related_to
        if raw:
            e = SemanticEntityMergeService._coerce_email(str(raw))
            if e:
                return e
        for rp in ext.related_persons or []:
            if rp.email:
                e = SemanticEntityMergeService._coerce_email(rp.email)
                if e:
                    return e
        return None

    @staticmethod
    def _coerce_email(raw: str) -> Optional[str]:
        if not raw:
            return None
        s = str(raw).strip()
        m = re.search(r"<([^>]+@[^>]+)>", s)
        if m:
            return m.group(1).strip().lower()
        if "@" in s and "." in s.split("@", 1)[-1]:
            core = s.split()[0] if s.split() else s
            if "@" in core:
                return core.lower()
        return None

    @staticmethod
    def _resolved_email_for_person(p: PersonRef) -> Optional[str]:
        """Email for merge keys and ``person_<email>`` ids: top-level or ``properties['email']``."""
        raw = p.email or (p.properties or {}).get("email")
        if not raw:
            return None
        n = normalize_email(str(raw))
        return n or None

    @staticmethod
    def _name_key_for_person(p: PersonRef) -> Optional[str]:
        nk = name_alias_key(p.name or (p.properties or {}).get("name"))
        return nk or None

    @staticmethod
    def _promote_email_from_name_peers(people: List[PersonRef]) -> List[PersonRef]:
        """Copy email onto name-only PersonRefs when another peer shares the same normalized name."""
        email_by_name: Dict[str, str] = {}
        for p in people:
            em = SemanticEntityMergeService._resolved_email_for_person(p)
            if not em:
                continue
            nk = SemanticEntityMergeService._name_key_for_person(p)
            if nk:
                email_by_name.setdefault(nk, em)

        if not email_by_name:
            return people

        out: List[PersonRef] = []
        for p in people:
            if SemanticEntityMergeService._resolved_email_for_person(p):
                out.append(p)
                continue
            nk = SemanticEntityMergeService._name_key_for_person(p)
            peer = email_by_name.get(nk) if nk else None
            if not peer:
                out.append(p)
                continue
            props = dict(p.properties or {})
            props.setdefault("email", peer)
            nm = normalize_email(peer) or peer.strip().lower()
            out.append(
                p.model_copy(
                    update={
                        "id": nm,
                        "email": nm,
                        "properties": props,
                    }
                )
            )
        return out

    @staticmethod
    def _merge_people_list_after_fold(
        people: List[PersonRef], extra: List[PersonRef]
    ) -> List[PersonRef]:
        """Dedupe by email, promote email from name peers, dedupe again."""
        merged = SemanticEntityMergeService._dedupe_people_by_email(people + extra)
        merged = SemanticEntityMergeService._promote_email_from_name_peers(merged)
        return SemanticEntityMergeService._dedupe_people_by_email(merged)

    @staticmethod
    def _dedupe_people_by_email(people: List[PersonRef]) -> List[PersonRef]:
        """Merge duplicate PersonRefs by email; combine property dicts."""
        with_email: Dict[str, PersonRef] = {}
        rest: List[PersonRef] = []

        for p in people:
            key = SemanticEntityMergeService._resolved_email_for_person(p)
            if not key:
                rest.append(p)
                continue
            if key not in with_email:
                with_email[key] = p.model_copy(
                    update={
                        "email": key,
                        "properties": {
                            **(p.properties or {}),
                            "email": key,
                        },
                    }
                )
                continue
            cur = with_email[key]
            merged_props = {**(cur.properties or {}), **(p.properties or {})}
            merged_props["email"] = key
            name = cur.name or p.name
            if p.name and cur.name and len(p.name) > len(cur.name):
                name = p.name
            elif p.name and not cur.name:
                name = p.name
            pr_cur = str(cur.role) if cur.role is not None else ""
            pr_new = str(p.role) if p.role is not None else ""
            role = cur.role
            if pr_cur == "mentioned" and pr_new != "mentioned":
                role = p.role
            with_email[key] = PersonRef(
                id=cur.id,
                name=name,
                email=key,
                role=role,
                avatar_url=p.avatar_url or cur.avatar_url,
                username=p.username or cur.username,
                properties=merged_props,
            )

        return list(with_email.values()) + rest

    async def apply_to_normalized_entities(
        self,
        db: AsyncSession,
        normalized: NormalizedEntity,
        sync_context: SyncContext,
    ) -> NormalizedEntity:
        """Fold person extractions, merge source entity + people + remaining extractions."""
        short_name = getattr(sync_context.connection, "short_name", "") or ""

        self._ensure_llm_call()

        normalized = self.fold_llm_person_extractions_into_people(normalized)

        if not settings.SEMANTIC_MERGE_ENABLED:
            sync_context.logger.debug(
                "[SemanticMerge] SEMANTIC_MERGE_ENABLED is false; skipping merge for entity_id=%s",
                normalized.entity_id,
            )
            return normalized

        sync_context.logger.debug(
            "[SemanticMerge] apply start entity_id=%s llm_extractions=%s people=%s shadow=%s",
            normalized.entity_id,
            len(normalized.llm_extractions),
            len(normalized.people),
            settings.SEMANTIC_MERGE_SHADOW_MODE,
        )

        org_id = sync_context.organization_id
        sync_id = sync_context.sync_id

        allow_full_entity_merge = settings.is_semantic_merge_allowed_for_connector(short_name)

        if allow_full_entity_merge:
            normalized = await self._merge_normalized_entity(
                db, org_id, sync_id, normalized, sync_context
            )

            merged_people: List[PersonRef] = []
            for p in normalized.people:
                merged_people.append(
                    await self._merge_person(db, org_id, sync_id, p, sync_context)
                )
            normalized = normalized.model_copy(update={"people": merged_people})

            new_extractions: List[LLMExtractionRef] = []
            for ext in normalized.llm_extractions:
                mext = await self._merge_llm_extraction(db, org_id, sync_id, ext, sync_context)
                new_rp: List[RelatedPersonRef] = []
                for rp in mext.related_persons or []:
                    new_rp.append(
                        await self._merge_related_person(db, org_id, sync_id, rp, sync_context)
                    )
                new_extractions.append(mext.model_copy(update={"related_persons": new_rp}))
            normalized = normalized.model_copy(update={"llm_extractions": new_extractions})
        else:
            # Structured (e.g. SQL) sources: do not merge the source row into the global semantic
            # pool, but still resolve every PersonRef (including LLM-folded persons) into PersonNode
            # so they share node_id / alias profiles with unstructured connectors.
            sync_context.logger.debug(
                "[SemanticMerge] connector %s is structured; PersonNode merge only",
                short_name,
            )
            merged_people_struct: List[PersonRef] = []
            for p in normalized.people:
                merged_people_struct.append(
                    await self._merge_person(db, org_id, sync_id, p, sync_context)
                )
            normalized = normalized.model_copy(update={"people": merged_people_struct})

        sync_context.logger.debug(
            "[SemanticMerge] apply done entity_id=%s", normalized.entity_id
        )
        return normalized

    async def _merge_normalized_entity(
        self,
        db: AsyncSession,
        org_id,
        sync_id,
        normalized: NormalizedEntity,
        sync_context: SyncContext,
    ) -> NormalizedEntity:
        """Resolve the source entity itself into the global semantic merge pool."""
        merge_entity_type = GLOBAL_MERGE_ENTITY_TYPE
        props = dict(normalized.properties or {})
        name_key = name_alias_key(normalized.name)
        canonical: Optional[str] = None
        method = "new_canonical"

        for alias_key in (name_key,):
            if canonical is None and alias_key:
                canonical = await entity_alias.get_canonical_by_alias_any_type(
                    db, organization_id=org_id, alias_key=alias_key
                )
                if canonical:
                    method = "alias_hit"

        text = extraction_text_for_embedding(
            name=normalized.name,
            description=normalized.description or normalized.content,
            extra=normalized.source_type,
        )
        q_emb = await self._embed(text, sync_context)

        if canonical is None and not settings.SEMANTIC_MERGE_SHADOW_MODE:
            resolved, vm = await self._resolve_with_vectors(
                db,
                org_id,
                merge_entity_type,
                text,
                q_emb,
                sync_context,
                candidate_name=normalized.name,
                candidate_desc=normalized.description or normalized.content,
            )
            if resolved:
                canonical = resolved
                method = vm

        if canonical is None:
            canonical = normalized.entity_id

        merged_props = {
            **props,
            "name": normalized.name,
            "description": normalized.description,
            "content": normalized.content,
            "source_type": normalized.source_type,
            "original_entity_id": normalized.entity_id,
            "original_entity_type": normalized.entity_type,
        }
        existing_profile = await entity_alias.get_profile(
            db,
            organization_id=org_id,
            entity_type=merge_entity_type,
            canonical_node_id=canonical,
        )
        base_json = existing_profile.merged_properties_json if existing_profile else {}
        merged, conflict = merge_dicts_deterministic(base_json, merged_props)
        description = normalized.description
        if conflict and self._llm_call and settings.SEMANTIC_MERGE_LLM_SYNTHESIS_ON_CONFLICT:
            description = await synthesize_summary_if_needed(
                title=normalized.name,
                text_a=normalized.description,
                text_b=merged.get("description") if isinstance(merged.get("description"), str) else None,
                llm_call=self._llm_call,
            ) or normalized.description

        if not settings.SEMANTIC_MERGE_SHADOW_MODE:
            if name_key:
                await entity_alias.upsert_alias_mapping(
                    db,
                    organization_id=org_id,
                    entity_type=merge_entity_type,
                    alias_key=name_key,
                    canonical_node_id=canonical,
                    confidence=0.95,
                    match_method=method,
                    last_seen_sync_id=sync_id,
                )
            emb = await self._embed(
                extraction_text_for_embedding(
                    name=normalized.name,
                    description=description or normalized.content,
                    extra=normalized.source_type,
                ),
                sync_context,
            )
            await entity_alias.upsert_canonical_profile(
                db,
                organization_id=org_id,
                entity_type=merge_entity_type,
                canonical_node_id=canonical,
                merged_properties_json=merged,
                merged_summary=description,
                embedding_text_hash=embedding_text_hash(text),
                embedding_json=emb,
            )

        merged_out = dict(normalized.properties or {})
        merged_out["semantic_canonical_node_id"] = canonical
        self._log_merge_resolution(
            sync_context,
            kind=normalized.entity_type,
            label=normalized.name or normalized.entity_id,
            canonical_node_id=canonical,
            match_method=method,
        )
        return normalized.model_copy(update={"properties": merged_out})

    def _ensure_llm_call(self) -> None:
        if self._llm_call is not None:
            return

        async def _call(prompt: str) -> str:
            try:
                from types import SimpleNamespace

                from contextd.platform.llm.gateway import (
                    LLMConfigurationError,
                    get_llm_gateway,
                )

                return await get_llm_gateway().complete(
                    [{"role": "user", "content": prompt}],
                    role="property_synthesis",
                    ctx=SimpleNamespace(logger=logger),
                )
            except LLMConfigurationError as e:
                logger.debug("Semantic merge LLM is not configured: %s", e)
                return ""
            except Exception as e:
                logger.warning(f"Semantic merge LLM call failed: {e}")
                return ""

        self._llm_call = _call

    async def _embed(self, text: str, sync_context: SyncContext) -> Optional[List[float]]:
        if not text.strip():
            return None
        try:
            from contextd.platform.embedders import DenseEmbedder

            vs = getattr(sync_context.collection, "vector_size", 1536) or 1536
            embedder = DenseEmbedder(vector_size=int(vs))
            vecs = await embedder.embed_many([text], sync_context)
            if vecs and len(vecs) == 1:
                return vecs[0]
        except Exception as e:
            sync_context.logger.debug(f"[SemanticMerge] Embed skipped: {e}")
        return None

    async def _merge_person(
        self,
        db: AsyncSession,
        org_id,
        sync_id,
        person: PersonRef,
        sync_context: SyncContext,
    ) -> PersonRef:
        """Resolve to a single graph ``node_id`` (``person_…``), merge profiles, set ``person.id``."""
        entity_type = PERSON_NODE_ENTITY_TYPE
        props = dict(person.properties or {})
        resolved_email = SemanticEntityMergeService._resolved_email_for_person(person)

        email_key = email_alias_key(resolved_email)
        name_key = name_alias_key(person.name or props.get("name"))

        resolved_id: Optional[str] = None
        match_method = "new_id"

        for ak in (email_key, name_key):
            if not ak:
                continue
            c = await entity_alias.get_canonical_by_alias(
                db, organization_id=org_id, entity_type=entity_type, alias_key=ak
            )
            if c:
                resolved_id = c
                match_method = "alias_hit"
                break

        display_name = (person.name or props.get("name") or "").strip()
        text = extraction_text_for_embedding(
            name=display_name,
            description=str(props.get("description", "")) or None,
            extra=resolved_email or "",
        )
        q_emb = await self._embed(text, sync_context)

        if resolved_id is None and not settings.SEMANTIC_MERGE_SHADOW_MODE:
            resolved, vm = await self._resolve_with_vectors(
                db,
                org_id,
                entity_type,
                text,
                q_emb,
                sync_context,
                candidate_name=display_name or None,
                candidate_desc=str(props.get("description", "")) or None,
            )
            if resolved:
                resolved_id = resolved
                match_method = vm

        if resolved_id is None:
            if resolved_email:
                resolved_id = f"person_{resolved_email}"
            else:
                resolved_id = f"person_{uuid.uuid4().hex[:12]}"
            match_method = "new_id"

        existing_profile = await entity_alias.get_profile(
            db,
            organization_id=org_id,
            entity_type=entity_type,
            canonical_node_id=resolved_id,
        )
        base_json = (
            dict(existing_profile.merged_properties_json)
            if existing_profile and existing_profile.merged_properties_json
            else {}
        )
        prop_email_raw = props.get("email")
        prop_email_norm = (
            normalize_email(str(prop_email_raw)) if prop_email_raw else ""
        )
        incoming_email = resolved_email or prop_email_norm or ""
        incoming = {
            **props,
            "name": display_name or (str(props.get("name")).strip() if props.get("name") else ""),
            "email": incoming_email,
        }
        merged_props, conflict = merge_dicts_deterministic(base_json, incoming)
        if resolved_email:
            merged_props["email"] = resolved_email
        elif merged_props.get("email"):
            e_raw = merged_props["email"]
            merged_props["email"] = normalize_email(str(e_raw)) or str(e_raw).strip().lower()
        if display_name:
            merged_props["name"] = display_name
        elif not merged_props.get("name"):
            merged_props["name"] = "Unknown"
        desc_a = base_json.get("description") if isinstance(base_json.get("description"), str) else None
        desc_b = incoming.get("description") if isinstance(incoming.get("description"), str) else None
        description_out = merged_props.get("description") if isinstance(merged_props.get("description"), str) else None
        if conflict and self._llm_call and settings.SEMANTIC_MERGE_LLM_SYNTHESIS_ON_CONFLICT:
            synthesized = await synthesize_summary_if_needed(
                title=str(merged_props.get("name") or display_name or "Person"),
                text_a=desc_a,
                text_b=desc_b,
                llm_call=self._llm_call,
            )
            if synthesized:
                merged_props["description"] = synthesized
                description_out = synthesized

        if not settings.SEMANTIC_MERGE_SHADOW_MODE:
            for ak in (email_key, name_key):
                if ak:
                    await entity_alias.upsert_alias_mapping(
                        db,
                        organization_id=org_id,
                        entity_type=entity_type,
                        alias_key=ak,
                        canonical_node_id=resolved_id,
                        confidence=1.0 if match_method == "alias_hit" else 0.9,
                        match_method=match_method,
                        last_seen_sync_id=sync_id,
                    )
            text_for_hash = json.dumps(merged_props, sort_keys=True, default=str)
            emb = await self._embed(text_for_hash[:2000], sync_context)
            await entity_alias.upsert_canonical_profile(
                db,
                organization_id=org_id,
                entity_type=entity_type,
                canonical_node_id=resolved_id,
                merged_properties_json=merged_props,
                merged_summary=description_out,
                embedding_text_hash=embedding_text_hash(text_for_hash),
                embedding_json=emb,
            )

        self._log_merge_resolution(
            sync_context,
            kind="PersonNode",
            label=resolved_email or person.name or person.id,
            canonical_node_id=resolved_id,
            match_method=match_method,
        )
        merged_props.pop("semantic_canonical_node_id", None)
        top_email = resolved_email or merged_props.get("email") or person.email
        if isinstance(top_email, str) and top_email:
            top_email = normalize_email(top_email) or top_email.strip().lower()
        return person.model_copy(
            update={
                "id": resolved_id,
                "name": merged_props.get("name") or person.name,
                "email": top_email if top_email else person.email,
                "properties": merged_props,
            }
        )

    async def _merge_related_person(
        self,
        db: AsyncSession,
        org_id,
        sync_id,
        rp: RelatedPersonRef,
        sync_context: SyncContext,
    ) -> RelatedPersonRef:
        fake = PersonRef(
            id=rp.email or "unknown",
            name=rp.name,
            email=rp.email,
            role=PersonRole.OTHER,
            properties={},
        )
        merged = await self._merge_person(db, org_id, sync_id, fake, sync_context)
        return rp.model_copy(update={"canonical_node_id": merged.id})

    async def _merge_llm_extraction(
        self,
        db: AsyncSession,
        org_id,
        sync_id,
        ext: LLMExtractionRef,
        sync_context: SyncContext,
    ) -> LLMExtractionRef:
        entity_type = ext.entity_type
        merge_entity_type = GLOBAL_MERGE_ENTITY_TYPE
        nk = name_alias_key(ext.name)
        email_key = email_alias_key((ext.properties or {}).get("email"))
        canonical: Optional[str] = None
        method = "new_canonical"
        profile_entity_type = entity_type

        for alias_key in (email_key, nk):
            if canonical is None and alias_key:
                c = await entity_alias.get_canonical_by_alias_any_type(
                    db, organization_id=org_id, alias_key=alias_key
                )
                if c:
                    canonical = c
                    method = "alias_hit"
                    profile_entity_type = merge_entity_type

        text = extraction_text_for_embedding(
            name=ext.name,
            description=ext.description,
            extra=(ext.properties or {}).get("email"),
        )
        q_emb = await self._embed(text, sync_context)

        if canonical is None and not settings.SEMANTIC_MERGE_SHADOW_MODE:
            resolved, vm = await self._resolve_with_vectors(
                db,
                org_id,
                merge_entity_type,
                text,
                q_emb,
                sync_context,
                candidate_name=ext.name,
                candidate_desc=ext.description,
            )
            if resolved:
                canonical = resolved
                method = vm

        if canonical is None:
            type_prefix = entity_type.lower().replace(":", "_")
            safe = (ext.name or "unknown").lower().strip().replace(" ", "_")
            canonical = f"{type_prefix}_{safe}"
            profile_entity_type = merge_entity_type

        merged_props = dict(ext.properties or {})
        existing_profile = await entity_alias.get_profile(
            db,
            organization_id=org_id,
            entity_type=profile_entity_type,
            canonical_node_id=canonical,
        )
        base_json = existing_profile.merged_properties_json if existing_profile else {}
        merged, conflict = merge_dicts_deterministic(base_json, merged_props)
        description = ext.description
        if conflict and self._llm_call and settings.SEMANTIC_MERGE_LLM_SYNTHESIS_ON_CONFLICT:
            description = await synthesize_summary_if_needed(
                title=ext.name,
                text_a=ext.description,
                text_b=merged.get("description") if isinstance(merged.get("description"), str) else None,
                llm_call=self._llm_call,
            ) or ext.description

        if not settings.SEMANTIC_MERGE_SHADOW_MODE:
            for alias_key in (email_key, nk):
                if alias_key:
                    await entity_alias.upsert_alias_mapping(
                        db,
                        organization_id=org_id,
                        entity_type=merge_entity_type,
                        alias_key=alias_key,
                        canonical_node_id=canonical,
                        confidence=0.95,
                        match_method=method,
                        last_seen_sync_id=sync_id,
                    )
            emb = await self._embed(
                extraction_text_for_embedding(
                    name=ext.name,
                    description=description,
                    extra=(merged.get("email") if isinstance(merged, dict) else None),
                ),
                sync_context,
            )
            await entity_alias.upsert_canonical_profile(
                db,
                organization_id=org_id,
                entity_type=profile_entity_type,
                canonical_node_id=canonical,
                merged_properties_json=merged,
                merged_summary=description,
                embedding_text_hash=embedding_text_hash(text),
                embedding_json=emb,
            )

        self._log_merge_resolution(
            sync_context,
            kind=entity_type,
            label=ext.name or ext.id,
            canonical_node_id=canonical,
            match_method=method,
        )
        return ext.model_copy(
            update={
                "id": canonical,
                "description": description,
                "properties": merged,
            }
        )

    async def _resolve_with_vectors(
        self,
        db: AsyncSession,
        org_id,
        entity_type: str,
        query_text: str,
        query_emb: Optional[List[float]],
        sync_context: SyncContext,
        *,
        candidate_name: Optional[str],
        candidate_desc: Optional[str],
    ) -> Tuple[Optional[str], str]:
        """Return (canonical_id, method) or (None, reason)."""
        if entity_type == GLOBAL_MERGE_ENTITY_TYPE:
            profiles = await entity_alias.list_profiles_any_type(
                db,
                organization_id=org_id,
                limit=500,
            )
        else:
            profiles = await entity_alias.list_profiles_for_entity_type(
                db,
                organization_id=org_id,
                entity_type=entity_type,
                limit=500,
            )
        if not query_emb or not profiles:
            return None, "no_vector_candidates"

        scored: List[Tuple[float, str]] = []
        for p in profiles:
            emb = p.embedding_json
            if not emb or not isinstance(emb, list):
                continue
            sim = cosine_similarity(query_emb, [float(x) for x in emb])
            if sim >= settings.SEMANTIC_MERGE_SIMILARITY_THRESHOLD:
                scored.append((sim, p.canonical_node_id))

        scored.sort(key=lambda x: -x[0])
        top_k = scored[: max(1, settings.SEMANTIC_MERGE_TOP_K)]
        if not top_k:
            return None, "below_threshold"

        best_sim, best_id = top_k[0]

        if settings.SEMANTIC_MERGE_LLM_JUDGE_ENABLED and self._llm_call:
            prof = (
                await entity_alias.get_profile_any_type(
                    db,
                    organization_id=org_id,
                    canonical_node_id=best_id,
                )
                if entity_type == GLOBAL_MERGE_ENTITY_TYPE
                else await entity_alias.get_profile(
                    db,
                    organization_id=org_id,
                    entity_type=entity_type,
                    canonical_node_id=best_id,
                )
            )
            cand_name = ""
            cand_desc = ""
            if prof and prof.merged_properties_json:
                cand_name = str(prof.merged_properties_json.get("name", ""))
                cand_desc = str(prof.merged_properties_json.get("description", ""))
            ok = await self._llm_same_entity(
                candidate_name or "",
                candidate_desc or "",
                cand_name,
                cand_desc,
            )
            if not ok:
                return None, "llm_reject"
        return best_id, f"vector_{best_sim:.3f}"

    async def _llm_same_entity(
        self,
        a_name: str,
        a_desc: str,
        b_name: str,
        b_desc: str,
    ) -> bool:
        assert self._llm_call is not None
        prompt = (
            "Decide if A and B refer to the same real-world entity.\n"
            'Reply with JSON only: {"same_entity": true|false}\n\n'
            f"A name: {a_name}\nA description: {a_desc}\n\n"
            f"B name: {b_name}\nB description: {b_desc}\n"
        )
        raw = await self._llm_call(prompt)
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(raw[start:end])
                return bool(data.get("same_entity"))
        except Exception:
            pass
        return False
