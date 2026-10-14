"""CTTI entity definitions."""

from contextd.platform.entities._base import WebEntity
from contextd.platform.entities._contextd_field import ContextDField


class CTTIWebEntity(WebEntity):
    """Web entity for CTTI clinical trials from ClinicalTrials.gov.

    This entity will be processed by the web_fetcher transformer to download
    the actual clinical trial content from ClinicalTrials.gov.
    """

    nct_id: str = ContextDField(
        ...,
        description="The NCT ID of the clinical trial study",
        is_entity_id=True,
        is_name=True,
    )
