"""CRUD operations for embedding models."""

from contextd.crud._base_public import CRUDPublic
from contextd.models.embedding_model import EmbeddingModel
from contextd.schemas.embedding_model import EmbeddingModelCreate, EmbeddingModelUpdate


class CRUDEmbeddingModel(CRUDPublic[EmbeddingModel, EmbeddingModelCreate, EmbeddingModelUpdate]):
    """CRUD operations for embedding models."""

    pass


embedding_model = CRUDEmbeddingModel(EmbeddingModel)
