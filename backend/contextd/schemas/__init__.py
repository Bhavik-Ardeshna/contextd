# flake8: noqa: F401
"""Schemas for the application."""

from contextd.platform.auth.schemas import OAuth2AuthUrl, OAuth2TokenResponse

from .admin import OrganizationMetrics
from .api_key import APIKey, APIKeyCreate, APIKeyInDBBase, APIKeyUpdate
from .auth import DevAuthLogin, DevAuthRegister, DevAuthToken
from .auth_provider import (
    AuthProvider,
    AuthProviderConnection,
    AuthProviderConnectionCreate,
    AuthProviderConnectionUpdate,
    AuthProviderCreate,
    AuthProviderUpdate,
)
from .billing_period import (
    BillingPeriod,
    BillingPeriodCreate,
    BillingPeriodStatus,
    BillingPeriodUpdate,
    BillingPeriodWithUsage,
    BillingTransition,
)
from .collection import (
    Collection,
    CollectionCreate,
    CollectionUpdate,
)
from .connection import Connection, ConnectionCreate, ConnectionInDBBase, ConnectionUpdate
from .context_forge import (
    ContextForgeDatabaseSummary,
    ContextForgeGraphPreview,
    ContextForgeGraphPreviewEdge,
    ContextForgeGraphPreviewNode,
    ContextForgeGraphSummary,
    ContextForgeMapping,
    ContextForgeMappingArtifact,
    ContextForgeMappingUpdate,
    ContextForgePipelineStep,
    ContextForgeSourceSummary,
)
from .context_intelligence import (
    ContextIntelligenceSource,
    ContextIntelligenceSummary,
    ContextQueryFeedbackRequest,
    ContextQueryFeedbackResponse,
)
from .destination import (
    Destination,
    DestinationCreate,
    DestinationInDBBase,
    DestinationUpdate,
    DestinationWithAuthenticationFields,
)
from .embedding_model import (
    EmbeddingModel,
    EmbeddingModelCreate,
    EmbeddingModelInDBBase,
    EmbeddingModelUpdate,
    EmbeddingModelWithAuthenticationFields,
)
from .entity import (
    Entity,
    EntityCount,
    EntityCreate,
    EntityInDBBase,
    EntityUpdate,
    EntityWithNormalized,
    NormalizedEntityData,
)
from .entity_count import EntityCount as EntityCountSchema
from .entity_count import EntityCountCreate, EntityCountUpdate, EntityCountWithDefinition
from .entity_definition import (
    EntityDefinition,
    EntityDefinitionCreate,
    EntityDefinitionUpdate,
    EntityType,
)
from .integration_credential import (
    IntegrationCredential,
    IntegrationCredentialCreate,
    IntegrationCredentialCreateEncrypted,
    IntegrationCredentialInDB,
    IntegrationCredentialRawCreate,
    IntegrationCredentialUpdate,
)
from .invitation import (
    InvitationBase,
    InvitationCreate,
    InvitationResponse,
    MemberResponse,
)
from .organization import (
    Organization,
    OrganizationBase,
    OrganizationCreate,
    OrganizationInDBBase,
    OrganizationUpdate,
    OrganizationWithRole,
)
from .organization_billing import (
    BillingPlan,
    BillingStatus,
    CancelSubscriptionRequest,
    CheckoutSessionRequest,
    CheckoutSessionResponse,
    CustomerPortalRequest,
    CustomerPortalResponse,
    MessageResponse,
    OrganizationBilling,
    OrganizationBillingCreate,
    OrganizationBillingUpdate,
    PaymentStatus,
    PlanLimits,
    SubscriptionInfo,
    UpdatePlanRequest,
)
from .search import SearchRequest, SearchResponse
from .search_query import (
    SearchQueryAnalytics,
    SearchQueryCreate,
    SearchQueryInsights,
    SearchQueryResponse,
    SearchQueryUpdate,
)
from .source import (
    Source,
    SourceCreate,
    SourceInDBBase,
    SourceUpdate,
)
from .source_connection import (
    AuthenticationDetails,
    AuthenticationMethod,
    EntitySummary,
    EntityTypeStats,
    ScheduleDetails,
    SourceConnection,
    SourceConnectionCreate,
    SourceConnectionJob,
    SourceConnectionListItem,
    SourceConnectionSimple,
    SourceConnectionUpdate,
    SyncDetails,
    SyncJobDetails,
)
from .source_connection_setup_draft import (
    DiscoveredField,
    DiscoveredObject,
    SourceConnectionSetupDraft,
    SourceConnectionSetupDraftCreate,
    SourceConnectionSetupDraftUpdate,
    SourceSetupDiscovery,
    SourceSetupDiscoverRequest,
    SourceSetupFinalizeRequest,
    SourceSetupScheduleRequest,
    SourceSetupScopeRequest,
    SourceSetupTestRequest,
    SourceSetupTestResult,
)
from .source_rate_limit import (
    SourceRateLimit,
    SourceRateLimitCreate,
    SourceRateLimitResponse,
    SourceRateLimitUpdate,
    SourceRateLimitUpdateRequest,
)
from .sync import (
    MinuteLevelScheduleConfig,
    ScheduleResponse,
    Sync,
    SyncBase,
    SyncCreate,
    SyncInDBBase,
    SyncUpdate,
    SyncWithoutConnections,
    SyncWithSourceConnection,
)
from .sync_cursor import (
    SyncCursor,
    SyncCursorBase,
    SyncCursorCreate,
    SyncCursorUpdate,
)
from .sync_job import (
    SyncJob,
    SyncJobCreate,
    SyncJobInDBBase,
    SyncJobUpdate,
)
from .transformer import Transformer, TransformerCreate, TransformerUpdate
from .usage import (
    SingleActionCheckResponse,
    Usage,
    UsageCreate,
    UsageInDBBase,
    UsageLimit,
    UsageUpdate,
)
from .user import (
    User,
    UserCreate,
    UserInDB,
    UserInDBBase,
    UserOrganization,
    UserUpdate,
    UserWithOrganizations,
)

# Rebuild models to resolve forward references
# This is necessary because OrganizationBilling references BillingPeriod as a string
OrganizationBilling.model_rebuild()
Organization.model_rebuild()
OrganizationWithRole.model_rebuild()
UserOrganization.model_rebuild()
User.model_rebuild()
