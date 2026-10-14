"""LLM enrichment service for extracting entities from unstructured content."""
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from contextd.platform.contexts.sync import SyncContext
from contextd.platform.entities._base import BaseEntity
from contextd.platform.entities._metadata import LLMExtractionConfig
from contextd.platform.sync.graph.schemas.llm_extraction import (
    ExtractedEntity,
    ExtractionResult,
)
from contextd.search.providers._base import BaseProvider


class LLMEnrichmentService:
    """Service for LLM-powered entity extraction from unstructured content fields.

    This service supports two extraction modes:

    1. PREDEFINED MODE (extract_people, extract_companies, etc.):
       - Extracts known entity types (Person, Company, Topic, etc.)
       - Uses fixed schema for extraction

    2. DYNAMIC MODE (dynamic_extraction=True):
       - LLM decides node types and edge types
       - Base node type with subtypes (e.g., EmailExtract:Task)
       - Custom edge types (e.g., ASSIGNS_TASK, MENTIONS_PROJECT)
       - Combines multiple fields using content_template

    Uses the EntityMetadata system with FieldMetadata.llm (LLMExtractionConfig).

    IMPORTANT: Extracted entities have CLEAN properties (no metadata).
    All extraction metadata is handled at the event level, not in the entity properties.
    """

    # System prompt for predefined entity extraction
    EXTRACTION_SYSTEM_PROMPT = """You are an expert at extracting structured entities and relationships from unstructured text.

Your task:
1. Analyze the provided content carefully
2. Extract ONLY entities that are explicitly mentioned or clearly implied
3. For each entity, extract the requested fields
4. Assign a confidence score (0.0-1.0) based on how certain you are
5. Extract relationships between the source document and extracted entities

Rules:
- Only extract entities that meet the confidence threshold (0.7 minimum)
- Use null for fields that aren't found
- Be precise - don't hallucinate information
- Consider context and implied relationships

Grounding (critical):
- Every extracted entity must correspond to a real, identifiable thing in the world—not a generic label, UI string, or automated system pretending to be a name.
- **Person** means a human being. Do not classify meeting platforms, calendar bots, noreply senders, or product names (e.g. Google Meet, Zoom, Teams) as Person; use Company, Product, or omit.
- **Company**, **Team**, **Product**, **Task**, etc. must be concrete instances you would track as distinct graph nodes, not boilerplate or mis-tagged types.
- When ambiguous, lower confidence or omit rather than invent."""

    # Injected into every predefined user extraction prompt (all connectors / field configs)
    EXTRACTION_REAL_ENTITY_APPENDIX = """REALITY AND TYPE CORRECTNESS (applies to every entity type below):
- Only extract nodes for real-world things worth tracking in a knowledge graph: specific people, real organizations, concrete work, named products, etc.
- **Person** = an actual human. Never output Person for: Google Meet, Zoom, Microsoft Teams, or similar products; calendar/meeting bots; noreply/no-reply addresses; mailing-list display names; or vendor boilerplate—unless they clearly identify a specific human (e.g. a real name with an individual email). If the sender or title is only a product/service, use **Product** or **Company** or do not extract.
- Do not confuse entity types: a video call product is not a Person; a generic "Meeting" word in a subject line is not automatically a Meeting node unless it is a real scheduled event worth tracking as you defined.
- Prefer omitting a doubtful extraction over guessing; use low confidence when you are not sure."""

    # System prompt for dynamic extraction
    DYNAMIC_EXTRACTION_SYSTEM_PROMPT = """You are an expert at extracting structured information and relationships from unstructured content.

Your task:
1. Analyze the content carefully to identify important information
2. Extract entities with appropriate subtypes based on what you find
3. Define meaningful relationships between entities
4. Assign confidence scores (0.0-1.0) based on certainty

Rules:
- Only extract information that is explicitly stated or clearly implied
- Create meaningful subtypes that describe what the entity represents
- Define relationship types that accurately describe how entities connect
- Be precise - don't hallucinate or make up information
- Consider the context and participants when defining relationships

Grounding:
- Extract only real-world entities. Person = human individuals, not products (Google Meet, Zoom), bots, or noreply senders. Use subtypes that match what the thing actually is."""

    PREDEFINED_EMAIL_EDGE_TYPES = {
        "EmailExtract:Person": "MENTIONS_PERSON",
        "EmailExtract:Task": "CONTAINS_TASK",
        "EmailExtract:Meeting": "SCHEDULES_MEETING",
        "EmailExtract:Project": "DISCUSSES_PROJECT",
        "EmailExtract:Decision": "MAKES_DECISION",
        "EmailExtract:Question": "ASKS_QUESTION",
        "EmailExtract:Deadline": "HAS_DEADLINE",
        "EmailExtract:Document": "REFERENCES_DOCUMENT",
        "EmailExtract:Company": "MENTIONS_COMPANY",
        "EmailExtract:Team": "MENTIONS_TEAM",
        "EmailExtract:Product": "MENTIONS_PRODUCT",
    }

    def __init__(self, provider: BaseProvider, sync_context: SyncContext):
        """Initialize the enrichment service.

        Args:
            provider: LLM provider (from search/providers) with structured_output support
            sync_context: Sync context for logging
        """
        self.provider = provider
        self.sync_context = sync_context
        self.logger = sync_context.logger
        self.model_name = self._provider_model_name()

    def _provider_model_name(self) -> str:
        """Return the provider model used for extraction metadata."""
        model_spec = getattr(self.provider, "model_spec", None)
        llm_model = getattr(model_spec, "llm_model", None)
        model_name = getattr(llm_model, "name", None)
        if model_name:
            return str(model_name)

        from contextd.platform.llm.gateway import configured_llm_model

        return configured_llm_model("extraction")

    async def enrich_entity(self, entity: BaseEntity) -> BaseEntity:
        """Enrich an entity by extracting structured data from LLM-enabled fields.

        Supports two modes:
        1. PREDEFINED: Extract known entity types (Person, Company, Topic, etc.)
        2. DYNAMIC: LLM decides node types/subtypes and edge types

        Attaches extracted data to:
        - entity._llm_extracted_entities: List[ExtractedEntity]
          Each entity has _edge_type in properties for graph edge creation
        - entity._llm_extraction_metadata: Dict[str, Any] (for tracking)

        Note: Normalizers convert _llm_extracted_entities to LLMExtractionRef
        which includes the edge_type for proper graph event generation.

        Args:
            entity: Entity to enrich

        Returns:
            Enriched entity with _llm_extracted_* attributes
        """
        all_extracted_entities: List[ExtractedEntity] = []
        extraction_metadata = {}

        # Get EntityMetadata from class
        entity_metadata = getattr(entity.__class__, "_entity_metadata", None)
        if not entity_metadata:
            # No metadata, nothing to extract
            entity._llm_extracted_entities = []
            entity._llm_extracted_relationships = []
            entity._llm_extraction_metadata = {}
            return entity

        fields_config = getattr(entity_metadata, "fields", {})
        for field_name, field_meta in fields_config.items():
            llm_config = getattr(field_meta, "llm", None)
            if not llm_config or not getattr(llm_config, "enabled", False):
                continue

            # Check extraction mode
            is_dynamic = llm_config.is_dynamic_mode() if hasattr(llm_config, 'is_dynamic_mode') else False

            if is_dynamic:
                # Dynamic mode: build content from template
                content = self._build_content_from_template(entity, llm_config)
                if not content or not content.strip():
                    continue

                self.logger.info(
                    f"[LLM Enrichment] Dynamic extraction from {entity.__class__.__name__} (combined fields)"
                )

                try:
                    extraction_result = await self._extract_dynamic(
                        entity=entity,
                        content=content,
                        llm_config=llm_config,
                    )
                    all_extracted_entities.extend(extraction_result.entities)

                    extraction_metadata["_dynamic"] = {
                        "model": extraction_result.model_used,
                        "duration_ms": extraction_result.extraction_duration_ms,
                        "entity_count": len(extraction_result.entities),
                        "relationship_count": len(extraction_result.relationships),
                        "mode": "dynamic",
                        "base_node_type": llm_config.base_node_type,
                    }

                    self.logger.info(
                        f"[LLM Enrichment] Extracted {len(extraction_result.entities)} dynamic entities "
                        f"in {extraction_result.extraction_duration_ms}ms"
                    )
                except Exception as e:
                    self.logger.error(
                        f"[LLM Enrichment] Failed dynamic extraction: {e}",
                        exc_info=True
                    )
                    continue
            else:
                # Predefined mode: extract from single field
                field_value = getattr(entity, field_name, None)
                if not field_value or not str(field_value).strip():
                    continue

                self.logger.info(
                    f"[LLM Enrichment] Predefined extraction from {entity.__class__.__name__}.{field_name}"
                )
                try:
                    extraction_result = await self._extract_from_field(
                        entity=entity,
                        field_name=field_name,
                        field_value=field_value,
                        llm_config=llm_config,
                    )
                    all_extracted_entities.extend(extraction_result.entities)

                    extraction_metadata[field_name] = {
                        "model": extraction_result.model_used,
                        "duration_ms": extraction_result.extraction_duration_ms,
                        "entity_count": len(extraction_result.entities),
                        "relationship_count": len(extraction_result.relationships),
                        "mode": "predefined",
                    }

                    self.logger.info(
                        f"[LLM Enrichment] Extracted {len(extraction_result.entities)} entities "
                        f"from {field_name} in {extraction_result.extraction_duration_ms}ms"
                    )
                except Exception as e:
                    self.logger.error(
                        f"[LLM Enrichment] Failed to extract from {field_name}: {e}",
                        exc_info=True
                    )
                    continue

        # Attach to entity
        # Note: Edge info is stored in each entity's _edge_type property
        # Normalizers will convert these to LLMExtractionRef for event generation
        entity._llm_extracted_entities = all_extracted_entities
        entity._llm_extraction_metadata = extraction_metadata

        return entity

    def _build_content_from_template(
        self,
        entity: BaseEntity,
        llm_config: LLMExtractionConfig
    ) -> str:
        """Build content string from template and entity fields.

        Args:
            entity: Entity with field values
            llm_config: Config with content_template and content_fields

        Returns:
            Formatted content string
        """
        template = llm_config.content_template
        if not template:
            # No template, just concatenate content_fields
            parts = []
            for field_name in llm_config.content_fields:
                value = getattr(entity, field_name, None)
                if value:
                    if isinstance(value, list):
                        value = ", ".join(str(v) for v in value)
                    parts.append(f"{field_name}: {value}")
            return "\n".join(parts)

        # Replace placeholders in template
        result = template
        for field_name in llm_config.content_fields:
            value = getattr(entity, field_name, None) or ""
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value)
            result = result.replace(f"{{{field_name}}}", str(value))

        return result

    async def _extract_dynamic(
        self,
        entity: BaseEntity,
        content: str,
        llm_config: LLMExtractionConfig,
    ) -> ExtractionResult:
        """Extract entities using dynamic mode - LLM decides types and edges.

        Args:
            entity: Source entity
            content: Combined content to analyze
            llm_config: Dynamic extraction config

        Returns:
            ExtractionResult with dynamic entities
        """
        start_time = time.time()

        # Build dynamic extraction prompt
        user_prompt = self._build_dynamic_extraction_prompt(
            entity_type=entity.__class__.__name__,
            content=content,
            base_node_type=llm_config.base_node_type,
            extraction_hint=llm_config.extraction_hint,
            confidence_threshold=llm_config.confidence_threshold,
        )

        # Build response schema for dynamic extraction
        extraction_schema = self._build_dynamic_pydantic_schema()

        # Call LLM
        try:
            llm_response = await self.provider.structured_output(
                messages=[
                    {"role": "system", "content": self.DYNAMIC_EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                schema=extraction_schema,
            )
        except Exception as e:
            self.logger.error(f"[LLM Enrichment] Dynamic LLM call failed: {e}")
            raise

        duration_ms = int((time.time() - start_time) * 1000)

        # Parse response
        return self._parse_dynamic_llm_response(
            llm_response=llm_response,
            base_node_type=llm_config.base_node_type,
            model_used=self.model_name,
            duration_ms=duration_ms,
            confidence_threshold=llm_config.confidence_threshold,
        )

    def _build_dynamic_extraction_prompt(
        self,
        entity_type: str,
        content: str,
        base_node_type: str,
        extraction_hint: Optional[str],
        confidence_threshold: float,
    ) -> str:
        """Build prompt for dynamic extraction."""
        # Truncate content if too long
        truncated_content = content[:10000]
        if len(content) > 10000:
            truncated_content += "\n\n[Content truncated...]"

        prompt = f"""Analyze this {entity_type} content and extract structured information:

CONTENT:
---
{truncated_content}
---

"""
        if extraction_hint:
            prompt += f"""
EXTRACTION GUIDANCE:
{extraction_hint}

"""

        prompt += f"""
{self.EXTRACTION_REAL_ENTITY_APPENDIX}

For each piece of important information you find, create an entity with:
1. subtype: A descriptive subtype (e.g., "ActionItem", "Project", "Deadline", "Decision", "Question")
2. name: A concise name/title for the entity
3. description: Brief description of what this entity represents
4. edge_type: How this entity relates to the source (e.g., "CONTAINS_ACTION_ITEM", "MENTIONS_PROJECT", "HAS_DEADLINE")
5. related_to: Who/what this entity relates to (e.g., person's email if assigned to someone)
6. confidence: Your confidence score (0.0-1.0)

The entities will be stored as "{base_node_type}:subtype" nodes.
Only include entities with confidence >= {confidence_threshold}.

Return as JSON with the schema provided."""

        return prompt

    def _build_dynamic_pydantic_schema(self) -> type[BaseModel]:
        """Build Pydantic schema for dynamic LLM structured output."""
        from pydantic import ConfigDict

        class DynamicEntityResponse(BaseModel):
            model_config = ConfigDict(extra='forbid')
            subtype: str  # e.g., "ActionItem", "Project", "Deadline"
            name: str
            description: Optional[str] = None
            edge_type: str  # e.g., "CONTAINS_ACTION_ITEM", "MENTIONS_PROJECT"
            related_to: Optional[str] = None  # e.g., email address if assigned to someone
            confidence: float

        class DynamicExtractionResponse(BaseModel):
            model_config = ConfigDict(extra='forbid')
            entities: List[DynamicEntityResponse] = []

        return DynamicExtractionResponse

    def _parse_dynamic_llm_response(
        self,
        llm_response: BaseModel,
        base_node_type: str,
        model_used: str,
        duration_ms: int,
        confidence_threshold: float,
    ) -> ExtractionResult:
        """Parse dynamic LLM response into ExtractionResult."""
        extracted_entities: List[ExtractedEntity] = []

        for entity_response in llm_response.entities:
            if entity_response.confidence < confidence_threshold:
                continue

            # Build full type with subtype: e.g., "EmailExtract:ActionItem"
            full_type = f"{base_node_type}:{entity_response.subtype}"

            # Build properties dict
            properties = {
                "name": entity_response.name,
                "subtype": entity_response.subtype,
            }
            if entity_response.description:
                properties["description"] = entity_response.description
            if entity_response.related_to:
                properties["related_to"] = entity_response.related_to

            # Store edge type in properties for later graph construction
            properties["_edge_type"] = entity_response.edge_type

            extracted_entities.append(
                ExtractedEntity(
                    type=full_type,
                    properties=properties,
                    confidence=entity_response.confidence,
                    source_field="_dynamic",
                )
            )

        return ExtractionResult(
            entities=extracted_entities,
            relationships=[],  # Relationships are handled by graph edges using _edge_type
            extraction_duration_ms=duration_ms,
            model_used=model_used,
        )

    async def _extract_from_field(
        self,
        entity: BaseEntity,
        field_name: str,
        field_value: Any,
        llm_config: LLMExtractionConfig,
    ) -> ExtractionResult:
        """Extract entities from a field using LLMExtractionConfig.

        Builds extraction based on boolean flags: extract_people, extract_companies, etc.
        """
        start_time = time.time()

        # Build extraction types from boolean flags
        extraction_types = []
        if getattr(llm_config, "extract_people", False):
            extraction_types.append({
                "type": "Person",
                "description": "People mentioned in the content",
                "fields": ["name", "email", "role", "title"],
            })
        if getattr(llm_config, "extract_companies", False):
            extraction_types.append({
                "type": "Company",
                "description": "Companies or organizations mentioned",
                "fields": ["name", "industry", "domain"],
            })
        if getattr(llm_config, "extract_topics", False):
            extraction_types.append({
                "type": "Topic",
                "description": "Topics, themes, or concepts discussed",
                "fields": ["name", "description"],
            })
        if getattr(llm_config, "extract_dates", False):
            extraction_types.append({
                "type": "Date",
                "description": "Dates, deadlines, or time references",
                "fields": ["name", "date_value", "context"],
            })
        if getattr(llm_config, "extract_locations", False):
            extraction_types.append({
                "type": "Location",
                "description": "Geographic locations or addresses",
                "fields": ["name", "address", "city", "country"],
            })
        if getattr(llm_config, "extract_products", False):
            extraction_types.append({
                "type": "Product",
                "description": "Products, services, or tools mentioned",
                "fields": ["name", "description", "category"],
            })

        # Add custom entity types
        for custom_type in getattr(llm_config, "custom_entity_types", []):
            extraction_types.append({
                "type": custom_type,
                "description": f"Custom entity type: {custom_type}",
                "fields": [
                    "name",
                    "email",
                    "role",
                    "title",
                    "description",
                    "status",
                    "due_date",
                    "meeting_date",
                    "assigned_to",
                    "owner",
                    "related_to",
                    "attendees",
                ],
            })

        if not extraction_types:
            # No extraction types enabled
            return ExtractionResult(
                entities=[],
                relationships=[],
                extraction_duration_ms=0,
                model_used="none",
            )

        # Build prompt
        confidence_threshold = getattr(llm_config, "confidence_threshold", 0.7)
        user_prompt = self._build_extraction_prompt(
            entity_type=entity.__class__.__name__,
            field_name=field_name,
            content=str(field_value),
            extraction_types=extraction_types,
            confidence_threshold=confidence_threshold,
            extraction_hint=getattr(llm_config, "extraction_hint", None),
        )

        # Build response schema
        extraction_schema = self._build_pydantic_schema()
        allowed_entity_types = {
            self._qualify_predefined_type(type_spec["type"], llm_config)
            for type_spec in extraction_types
        }

        # Call LLM
        try:
            llm_response = await self.provider.structured_output(
                messages=[
                    {"role": "system", "content": self.EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                schema=extraction_schema,
            )
        except Exception as e:
            self.logger.error(f"[LLM Enrichment] LLM call failed: {e}")
            raise

        duration_ms = int((time.time() - start_time) * 1000)

        # Parse response
        return self._parse_llm_response(
            llm_response=llm_response,
            field_name=field_name,
            model_used=self.model_name,
            duration_ms=duration_ms,
            confidence_threshold=confidence_threshold,
            allowed_entity_types=allowed_entity_types,
            llm_config=llm_config,
        )

    def _build_extraction_prompt(
        self,
        entity_type: str,
        field_name: str,
        content: str,
        extraction_types: List[Dict[str, Any]],
        confidence_threshold: float,
        extraction_hint: Optional[str] = None,
    ) -> str:
        """Build extraction prompt for LLM."""
        # Truncate content if too long
        truncated_content = content[:10000]
        if len(content) > 10000:
            truncated_content += "\n\n[Content truncated...]"

        prompt = f"""Extract structured information from this {entity_type}.{field_name} content:

CONTENT:
---
{truncated_content}
---
"""
        if extraction_hint and extraction_hint.strip():
            prompt += f"""
EXTRACTION GUIDANCE:
{extraction_hint.strip()}

"""

        prompt += f"""
{self.EXTRACTION_REAL_ENTITY_APPENDIX}

Extract the following entity types:
"""
        for entity_spec in extraction_types:
            prompt += f"""
- {entity_spec['type']}: {entity_spec['description']}
  Fields to extract: {', '.join(entity_spec['fields'])}
"""

        prompt += f"""
Return as JSON with the schema provided.
Include a confidence score (0.0-1.0) for each extracted entity.
Only include entities with confidence >= {confidence_threshold}.
"""
        return prompt

    def _build_pydantic_schema(self) -> type[BaseModel]:
        """Build Pydantic schema for LLM structured output."""
        from pydantic import ConfigDict

        class ExtractedEntityResponse(BaseModel):
            model_config = ConfigDict(extra='forbid')
            type: str
            name: Optional[str] = None
            email: Optional[str] = None
            role: Optional[str] = None
            title: Optional[str] = None
            industry: Optional[str] = None
            domain: Optional[str] = None
            description: Optional[str] = None
            date_value: Optional[str] = None
            context: Optional[str] = None
            address: Optional[str] = None
            city: Optional[str] = None
            country: Optional[str] = None
            category: Optional[str] = None
            status: Optional[str] = None
            due_date: Optional[str] = None
            meeting_date: Optional[str] = None
            assigned_to: Optional[str] = None
            owner: Optional[str] = None
            related_to: Optional[str] = None
            attendees: List[str] = []
            confidence: float

        class ExtractionResponse(BaseModel):
            model_config = ConfigDict(extra='forbid')
            entities: List[ExtractedEntityResponse] = []

        return ExtractionResponse

    def _parse_llm_response(
        self,
        llm_response: BaseModel,
        field_name: str,
        model_used: str,
        duration_ms: int,
        confidence_threshold: float,
        allowed_entity_types: Optional[set[str]] = None,
        llm_config: Optional[LLMExtractionConfig] = None,
    ) -> ExtractionResult:
        """Parse LLM response into ExtractionResult."""
        extracted_entities: List[ExtractedEntity] = []

        for entity_response in llm_response.entities:
            if entity_response.confidence < confidence_threshold:
                continue

            entity_type = self._qualify_predefined_type(entity_response.type, llm_config)
            if allowed_entity_types and entity_type not in allowed_entity_types:
                self.logger.debug(
                    "[LLM Enrichment] Skipping unsupported predefined type '%s' for field '%s'",
                    entity_response.type,
                    field_name,
                )
                continue

            # Build properties dict
            properties = {}
            for field in ["name", "email", "role", "title", "industry", "domain",
                          "description", "date_value", "context", "address",
                          "city", "country", "category", "status", "due_date",
                          "meeting_date", "assigned_to", "owner", "related_to", "attendees"]:
                value = getattr(entity_response, field, None)
                if value is not None:
                    properties[field] = value

            properties["_edge_type"] = self._default_edge_type_for_extracted(entity_type)

            extracted_entities.append(
                ExtractedEntity(
                    type=entity_type,
                    properties=properties,
                    confidence=entity_response.confidence,
                    source_field=field_name,
                )
            )

        return ExtractionResult(
            entities=extracted_entities,
            relationships=[],  # Relationships are handled by graph edges
            extraction_duration_ms=duration_ms,
            model_used=model_used,
        )

    def _qualify_predefined_type(
        self,
        entity_type: str,
        llm_config: Optional[LLMExtractionConfig],
    ) -> str:
        """Apply the configured base node type to predefined extraction types."""
        if not entity_type:
            return entity_type
        if ":" in entity_type:
            return entity_type
        if llm_config and llm_config.base_node_type:
            return f"{llm_config.base_node_type}:{entity_type}"
        return entity_type

    def _default_edge_type_for_extracted(self, entity_type: str) -> str:
        """Return a deterministic edge type for curated predefined extractions."""
        return self.PREDEFINED_EMAIL_EDGE_TYPES.get(entity_type, "EXTRACTED_FROM")
