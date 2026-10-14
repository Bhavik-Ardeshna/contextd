import { lazy, Suspense, useEffect } from 'react';
import { ThemeProvider } from '@/lib/theme-provider';
import { Routes, Route } from 'react-router-dom';
import { Toaster } from 'sonner';
import { Database, Loader2, Sparkles } from 'lucide-react';
import '@/styles/toast.css';

import DashboardLayout from '@/components/DashboardLayout';
import { useCollectionsStore } from '@/lib/stores';
import { AuthGuard } from '@/components/AuthGuard';
import { protectedPaths, publicPaths } from '@/constants/paths';

const Dashboard = lazy(() => import('@/pages/Dashboard'));
const DatabasesPage = lazy(() => import('@/pages/DatabasesPage'));
const SourcesPage = lazy(() => import('@/pages/SourcesPage'));
const SourceSetupPage = lazy(() => import('@/pages/SourceSetupPage'));
const CollectionDetailView = lazy(() => import('@/pages/CollectionDetailView'));
const AuthProviders = lazy(() => import('@/pages/AuthProviders'));
const SemanticMcp = lazy(() => import('@/pages/SemanticMcp'));
const Login = lazy(() => import('@/pages/Login'));
const Callback = lazy(() => import('@/pages/Callback'));
const AuthCallback = lazy(() =>
  import('@/pages/AuthCallback').then((module) => ({ default: module.AuthCallback }))
);
const OrganizationSettingsUnified = lazy(() =>
  import('@/pages/organization/OrganizationSettingsUnified').then((module) => ({
    default: module.OrganizationSettingsUnified,
  }))
);
const Onboarding = lazy(() => import('@/pages/Onboarding'));
const BillingSuccess = lazy(() => import('@/pages/BillingSuccess'));
const BillingCancel = lazy(() => import('@/pages/BillingCancel'));
const BillingSetup = lazy(() => import('@/pages/BillingSetup'));
const BillingPortal = lazy(() => import('@/pages/BillingPortal'));
const AdminDashboard = lazy(() =>
  import('@/pages/AdminDashboard').then((module) => ({ default: module.AdminDashboard }))
);
const GraphPage = lazy(() =>
  import('@/pages/GraphPage').then((module) => ({ default: module.GraphPage }))
);
const ChatPage = lazy(() => import('@/pages/ChatPage'));
const QueryConsolePage = lazy(() => import('@/pages/QueryConsolePage'));
const SavedQueriesPage = lazy(() => import('@/pages/SavedQueriesPage'));
const CohortCreationPage = lazy(() => import('@/pages/CohortCreationPage'));
const NotFound = lazy(() =>
  import('@/pages/NotFound').then((module) => ({ default: module.NotFound }))
);

function PageFallback() {
  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <aside className="hidden w-[244px] shrink-0 border-r border-border bg-card px-4 py-4 lg:block">
        <div className="text-[25px] font-semibold leading-none tracking-normal">
          Context<span className="text-primary">D</span>
        </div>
        <div className="mt-8 space-y-5">
          {['Workspace', 'Operations', 'Settings'].map((section) => (
            <div key={section}>
              <div className="mb-2 h-3 w-20 rounded bg-muted" />
              <div className="space-y-2">
                <div className="h-9 rounded-md bg-primary/10" />
                <div className="h-9 rounded-md bg-muted/55" />
                <div className="h-9 rounded-md bg-muted/35" />
              </div>
            </div>
          ))}
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-[52px] shrink-0 items-center justify-between border-b border-border bg-card px-4">
          <div className="h-5 w-32 rounded bg-muted" />
          <div className="flex items-center gap-2">
            <div className="hidden h-8 w-56 rounded-md border border-border bg-background md:block" />
            <div className="h-8 w-20 rounded-md border border-green-500/20 bg-green-500/10" />
          </div>
        </header>
        <main className="flex flex-1 items-center justify-center p-6">
          <div className="w-full max-w-md rounded-lg border border-border bg-card p-5 shadow-sm">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-md border border-primary/20 bg-primary/10 text-primary">
                <Database className="h-5 w-5" />
              </div>
              <div>
                <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                  Loading ContextD
                  <Loader2 className="h-4 w-4 animate-spin text-primary" />
                </div>
                <p className="mt-1 text-xs text-muted-foreground">Preparing the workspace view.</p>
              </div>
            </div>
            <div className="mt-5 space-y-2">
              {[72, 100, 56].map((width, index) => (
                <div key={width} className="h-2 rounded-full bg-muted">
                  <div
                    className="h-full rounded-full bg-primary/70"
                    style={{ width: `${index === 1 ? 100 : width}%` }}
                  />
                </div>
              ))}
            </div>
            <div className="mt-4 flex items-center gap-2 rounded-md border border-primary/20 bg-primary/5 px-3 py-2 text-xs text-muted-foreground">
              <Sparkles className="h-3.5 w-3.5 text-primary" />
              Loading data, routes, and active graph state
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}

function App() {
  // Initialize collections event listeners when the app loads
  useEffect(() => {
    const unsubscribe = useCollectionsStore.getState().subscribeToEvents();
    return unsubscribe;
  }, []);

  return (
    <ThemeProvider defaultTheme="system" storageKey="contextd-ui-theme">
      <Suspense fallback={<PageFallback />}>
        <Routes>
          {/* Public routes */}
          <Route path={publicPaths.login} element={<Login />} />
          <Route path={publicPaths.callback} element={<Callback />} />
          <Route path={publicPaths.semanticMcp} element={<SemanticMcp />} />
          <Route path={publicPaths.onboarding} element={<Onboarding />} />
          <Route path={publicPaths.billingSuccess} element={<BillingSuccess />} />
          <Route path={publicPaths.billingCancel} element={<BillingCancel />} />

          {/* Auth callback routes - OUTSIDE of DashboardLayout */}
          {/* <Route path="/auth/callback/:short_name" element={<AuthCallback />} /> */}
          <Route path="/auth/callback" element={<AuthCallback />} />

          {/* Protected routes */}
          <Route element={<AuthGuard><DashboardLayout /></AuthGuard>}>
            <Route path={protectedPaths.dashboard} element={<DatabasesPage />} />
            <Route path={protectedPaths.databases} element={<DatabasesPage />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path={protectedPaths.sources} element={<SourcesPage />} />
            <Route path={protectedPaths.sourceSetup} element={<SourceSetupPage />} />

            <Route path="/collections/:readable_id/query" element={<QueryConsolePage />} />
            <Route path="/databases/:readable_id/query" element={<QueryConsolePage />} />
            <Route path="/collections/:readable_id/:tab" element={<CollectionDetailView />} />
            <Route path={protectedPaths.collectionDetail} element={<CollectionDetailView />} />
            <Route path="/databases/:readable_id/:tab" element={<CollectionDetailView />} />
            <Route path={protectedPaths.databaseDetail} element={<CollectionDetailView />} />
            <Route path={protectedPaths.apiKeys} />
            <Route path={protectedPaths.authProviders} element={<AuthProviders />} />
            <Route path={protectedPaths.mcp} element={<SemanticMcp />} />

            {/* Organization routes */}
            <Route path="/organization/settings" element={<OrganizationSettingsUnified />} />

            {/* Billing routes */}
            <Route path="/billing/setup" element={<BillingSetup />} />
            <Route path="/billing/portal" element={<BillingPortal />} />

            {/* Admin routes */}
            <Route path="/admin" element={<AdminDashboard />} />

            {/* Graph routes */}
            <Route path={protectedPaths.graph} element={<GraphPage />} />

            <Route path={protectedPaths.cohortCreation} element={<CohortCreationPage />} />

            {/* Chat routes */}
            <Route path={protectedPaths.query} element={<QueryConsolePage />} />
            <Route path={protectedPaths.savedQueries} element={<SavedQueriesPage />} />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/chat/:chatId" element={<ChatPage />} />
          </Route>
          <Route path="*" element={<NotFound />} />
        </Routes>
      </Suspense>
      <Toaster
        richColors
        position="top-right"
        expand={false}
        closeButton
        toastOptions={{
          style: {
            background: 'hsl(var(--background))',
            border: '1px solid hsl(var(--border))',
            borderRadius: '12px',
            boxShadow: '0 10px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)',
            fontSize: '14px',
            fontWeight: '500',
            color: 'hsl(var(--foreground))',
          },
          className: 'toast-custom',
          duration: 4000,
        }}
        theme="system"
      />
    </ThemeProvider>
  );
}

export default App;
