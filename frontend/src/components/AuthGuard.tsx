import { useEffect, useState, useRef } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '@/lib/auth-context';
import { useOrganizationStore } from '@/lib/stores/organizations';
import { Database, Loader2, Sparkles } from 'lucide-react';
import authConfig from '@/config/auth';
import { publicPaths } from '@/constants/paths';

interface AuthGuardProps {
  children: React.ReactNode;
}

export const AuthGuard = ({ children }: AuthGuardProps) => {
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  // This state is crucial to prevent rendering children before the org check is complete
  const [canRenderChildren, setCanRenderChildren] = useState(false);
  const initializationAttempted = useRef(false);

  useEffect(() => {
    // Auth disabled mode: skip login, go straight to org initialization
    if (authConfig.authDisabled) {
      if (authLoading) return;

      if (!initializationAttempted.current) {
        initializationAttempted.current = true;
        useOrganizationStore.getState().initializeOrganizations()
          .then((orgs) => {
            if (orgs.length > 0) {
              setCanRenderChildren(true);
            } else {
              navigate(publicPaths.onboarding, { replace: true });
            }
          })
          .catch(() => {
            navigate(publicPaths.onboarding, { replace: true });
          });
      }
      return;
    }

    // Dev auth mode: require authentication, then load orgs
    if (authConfig.devAuthEnabled) {
      if (authLoading) return; // Still loading, wait

      if (!isAuthenticated) {
        navigate(publicPaths.login, { replace: true });
        return;
      }

      // Authenticated via dev auth, initialize organizations
      if (!initializationAttempted.current) {
        initializationAttempted.current = true;
        useOrganizationStore.getState().initializeOrganizations()
          .then((orgs) => {
            if (orgs.length > 0) {
              setCanRenderChildren(true);
            } else {
              navigate(publicPaths.onboarding, { replace: true });
            }
          })
          .catch(() => {
            navigate(publicPaths.onboarding, { replace: true });
          });
      }
      return;
    }

    // Handle unauthenticated users first (Auth0 mode)
    if (!authLoading && !isAuthenticated) {
      // Allow access to login/callback pages without redirecting
      if (location.pathname !== publicPaths.login && location.pathname !== publicPaths.callback) {
        navigate(publicPaths.login, { replace: true });
      }
      return;
    }

    // Start organization check for authenticated users
    if (isAuthenticated && !authLoading && !initializationAttempted.current) {
      initializationAttempted.current = true;

      useOrganizationStore.getState().initializeOrganizations()
        .then(async (fetchedOrganizations) => {
          if (fetchedOrganizations.length > 0) {
            // Check billing status after organizations are loaded
            const billingCheck = await useOrganizationStore.getState().checkBillingStatus();

            // Always allow access - billing issues are handled per-org
            setCanRenderChildren(true);
          } else {
            // User has no orgs, redirect them
            navigate(publicPaths.onboarding, { replace: true });
          }
        })
        .catch(() => {
          navigate(publicPaths.onboarding, { replace: true });
        });
    }
  }, [isAuthenticated, authLoading, navigate, location.pathname]);

  // Show a loading spinner during the initial auth check or org fetch
  if (!canRenderChildren && (authLoading || (isAuthenticated && !initializationAttempted.current))) {
     // A special check to prevent a flash of the loader on the onboarding page
    if (location.pathname === publicPaths.onboarding) {
      return null;
    }
    return (
      <div className="flex h-screen w-full items-center justify-center bg-background p-6">
        <div className="w-full max-w-sm rounded-lg border border-border bg-card p-5 shadow-sm">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-primary/20 bg-primary/10 text-primary">
              <Database className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <p className="text-sm font-semibold text-foreground">Preparing ContextD</p>
              <p className="mt-0.5 text-xs text-muted-foreground">Checking auth, workspace, and graph state.</p>
            </div>
            <Loader2 className="ml-auto h-4 w-4 shrink-0 animate-spin text-primary" />
          </div>
          <div className="mt-4 space-y-2">
            <div className="h-2 rounded-full bg-muted">
              <div className="h-full w-2/3 animate-pulse rounded-full bg-primary" />
            </div>
            <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
              <Sparkles className="h-3.5 w-3.5 text-primary" />
              Loading the active organization shell
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Render children ONLY when the check is complete and successful
  if (canRenderChildren) {
    return <>{children}</>;
  }

  // Render nothing while redirecting or for unauthenticated users on public parts of the app
  return null;
};
