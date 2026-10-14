"""CRUD operations for transformers."""

from contextd.crud._base_public import CRUDPublic
from contextd.models.transformer import Transformer
from contextd.schemas.transformer import TransformerCreate, TransformerUpdate


class CRUDTransformer(CRUDPublic[Transformer, TransformerCreate, TransformerUpdate]):
    """CRUD operations for Transformer."""

    pass


transformer = CRUDTransformer(Transformer)
