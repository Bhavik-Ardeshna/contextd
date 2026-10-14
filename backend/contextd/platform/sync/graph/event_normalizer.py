"""Graph event normalizer - ensures all events follow the same schema."""
from typing import List

from contextd.schemas.graph_event import TypedGraphEvent


class GraphEventNormalizer:
    """Normalizes graph events to ensure consistent schema.

    All events (structured field events and LLM-extracted events) pass through
    this normalizer to ensure they have identical structure. The only difference
    is in the event.metadata field, which tracks the extraction source and method.
    """

    def normalize_structured_event(
        self,
        event: TypedGraphEvent,
    ) -> TypedGraphEvent:
        """Normalize an event from structured field (graph_config).

        Adds standard metadata tracking:
        - extraction_source: "structured"
        - extraction_method: "field_mapping"

        Args:
            event: Event from structured field processing

        Returns:
            Normalized event with metadata
        """
        event.metadata = event.metadata or {}
        event.metadata.update({
            "extraction_source": "structured",
            "extraction_method": "field_mapping",
        })
        return event

    def normalize_llm_event(
        self,
        event: TypedGraphEvent,
        extraction_confidence: float,
        extraction_model: str,
    ) -> TypedGraphEvent:
        """Normalize an event from LLM extraction.

        Adds LLM-specific metadata at event level:
        - extraction_source: "llm"
        - extraction_method: extraction_model
        - extraction_confidence: float

        IMPORTANT: Node/edge properties remain clean (no metadata).
        All extraction metadata is stored at the event level.

        Args:
            event: Event from LLM extraction
            extraction_confidence: Confidence score from LLM (0.0-1.0)
            extraction_model: Configured model used for extraction

        Returns:
            Normalized event with LLM metadata
        """
        event.metadata = event.metadata or {}
        event.metadata.update({
            "extraction_source": "llm",
            "extraction_method": extraction_model,
            "extraction_confidence": extraction_confidence,
        })
        return event

    def normalize_batch(
        self,
        events: List[TypedGraphEvent],
    ) -> List[TypedGraphEvent]:
        """Normalize a batch of events.

        This is the final step before storage - ensures ALL events
        have consistent schema regardless of source.

        Performs final validation:
        - Ensures all events have metadata dict
        - Ensures all events have extraction_source field
        - Sets default values for missing metadata

        Args:
            events: List of events to normalize

        Returns:
            Normalized events ready for storage
        """
        normalized = []
        for event in events:
            # Events already have metadata set by generate methods
            # This is a final validation pass
            if not event.metadata:
                event.metadata = {}

            # Validate required metadata fields
            if "extraction_source" not in event.metadata:
                event.metadata["extraction_source"] = "unknown"

            normalized.append(event)

        return normalized
