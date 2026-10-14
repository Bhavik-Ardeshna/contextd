export const protectedPaths = {
    dashboard: "/",
    sources: "/sources",
    sourceSetup: "/sources/:provider/setup",
    collections: "/collections",
    collectionDetail: "/collections/:readable_id",
    databases: "/databases",
    databaseDetail: "/databases/:readable_id",
    collectionNew: "/collections/:readable_id/new",
    query: "/query",
    savedQueries: "/saved-queries",
    apiKeys: "/api-keys",
    authProviders: "/auth-providers",
    authCallback: "/auth/callback/:short_name",
    graph: "/graph",
    cohortCreation: "/cohorts",
    mcp: "/mcp",
}

export const publicPaths = {
    login: "/login",
    callback: "/callback",
    semanticMcp: "/semantic-mcp",
    onboarding: "/onboarding",
    billingSuccess: "/billing/success",
    billingCancel: "/billing/cancel",
}
