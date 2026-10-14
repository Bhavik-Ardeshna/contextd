"""CRUD operations for auth providers."""

from contextd.crud._base_public import CRUDPublic
from contextd.models.auth_provider import AuthProvider
from contextd.schemas.auth_provider import AuthProviderCreate, AuthProviderUpdate


class CRUDAuthProvider(CRUDPublic[AuthProvider, AuthProviderCreate, AuthProviderUpdate]):
    """CRUD operations for auth providers."""

    pass


# Create instance for use in endpoints
auth_provider = CRUDAuthProvider(AuthProvider)
