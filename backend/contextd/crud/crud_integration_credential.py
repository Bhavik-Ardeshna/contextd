"""CRUD operations for integration credentials."""

from contextd.crud._base_organization import CRUDBaseOrganization
from contextd.models.integration_credential import IntegrationCredential
from contextd.schemas.integration_credential import (
    IntegrationCredentialCreateEncrypted,
    IntegrationCredentialUpdate,
)


class CRUDIntegrationCredential(
    CRUDBaseOrganization[
        IntegrationCredential, IntegrationCredentialCreateEncrypted, IntegrationCredentialUpdate
    ]
):
    """CRUD operations for integration credentials."""


integration_credential = CRUDIntegrationCredential(IntegrationCredential)
