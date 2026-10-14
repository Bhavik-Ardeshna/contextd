"""Admin API router composition."""

from contextd.api.router import TrailingSlashRouter
from contextd.api.v1.endpoints.admin_feature_flags import router as feature_flags_router
from contextd.api.v1.endpoints.admin_organization_billing import (
    router as organization_billing_router,
)
from contextd.api.v1.endpoints.admin_organizations import router as organizations_router
from contextd.api.v1.endpoints.admin_search import router as search_router
from contextd.api.v1.endpoints.admin_sync_lifecycle import router as sync_lifecycle_router
from contextd.api.v1.endpoints.admin_sync_listing import router as sync_listing_router
from contextd.api.v1.endpoints.admin_sync_resync import router as sync_resync_router

router = TrailingSlashRouter()
router.include_router(feature_flags_router)
router.include_router(organization_billing_router)
router.include_router(organizations_router)
router.include_router(search_router)
router.include_router(sync_resync_router)
router.include_router(sync_listing_router)
router.include_router(sync_lifecycle_router)
