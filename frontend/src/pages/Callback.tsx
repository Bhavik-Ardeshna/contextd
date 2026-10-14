import { useAuth0 } from '@auth0/auth0-react';
import { useEffect, useRef, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Loader2, AlertTriangle, Mail, HelpCircle } from 'lucide-react';
import { apiClient } from '@/lib/api';
import { useAuth } from '@/lib/auth-context';

const Callback = () => {
  const {
    isLoading: auth0Loading,
    isAuthenticated,
    error,
    user,
    logout,
  } = useAuth0();
  const { getToken, isLoading: authContextLoading } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const organizationName = location.state?.appState?.organizationName;

  // Track if we've already attempted to sync to prevent duplicates
  const syncAttempted = useRef(false);

  // State for handling Auth0 ID conflicts
  const [authConflictError, setAuthConflictError] = useState<{
    message: string;
    existingAuth0Id: string;
    incomingAuth0Id: string;
  } | null>(null);

  // Combine both loading states
  const isLoading = auth0Loading || authContextLoading;

  // Function to handle logout - just log out, don't specify returnTo
  const handleLogout = () => {
    logout();
  };

  // Create or update user in backend when authenticated
  useEffect(() => {
    const syncUser = async () => {
      // Only attempt if authenticated, have user data, not loading, and haven't already attempted
      if (isAuthenticated && user && !isLoading && !syncAttempted.current) {
        syncAttempted.current = true; // Mark as attempted to prevent duplicates

        try {
          // Token is now managed by auth context
          const token = await getToken();

          if (!token) {
            const returnTo = sessionStorage.getItem('auth_return_to');
            if (returnTo) sessionStorage.removeItem('auth_return_to');
            navigate(returnTo || '/');
            return;
          }

          const userData = {
            email: user.email,
            full_name: user.name,
            picture: user.picture,
            auth0_id: user.sub,
            email_verified: user.email_verified,
          };

          // Call backend API to create or update user
          const response = await apiClient.post('/users/create_or_update', userData);

          if (!response.ok) {
            const errorData = await response.json();

            // Check for Auth0 ID conflict
            if (response.status === 409 && errorData.detail?.error === 'auth0_id_conflict') {
              setAuthConflictError({
                message: errorData.detail.message,
                existingAuth0Id: errorData.detail.existing_auth0_id,
                incomingAuth0Id: errorData.detail.incoming_auth0_id,
              });
              return; // Don't redirect, show the error
            }
          }

          // Redirect to return URL (e.g. after OAuth connector flow) or home
          const returnTo = sessionStorage.getItem('auth_return_to');
          if (returnTo) sessionStorage.removeItem('auth_return_to');
          navigate(returnTo || '/');
        } catch {
          const returnTo = sessionStorage.getItem('auth_return_to');
          if (returnTo) sessionStorage.removeItem('auth_return_to');
          navigate(returnTo || '/');
        }
      }
    };

    syncUser();
  }, [isAuthenticated, user, isLoading, navigate]); // Removed getToken from dependencies

  // Auto-logout after showing Auth0 conflict error
  useEffect(() => {
    if (authConflictError) {
      const timer = setTimeout(() => {
        logout();
      }, 10000); // Logout after 10 seconds

      return () => clearTimeout(timer);
    }
  }, [authConflictError, logout]);

  // Auto-redirect to login if there's an error (and log out first)
  useEffect(() => {
    if (error && !isLoading) {
      handleLogout();
    }
  }, [error, isLoading]);

  // Non-authenticated state - auto redirect after a short delay
  useEffect(() => {
    if (!isAuthenticated && !isLoading && !error) {
      const timer = setTimeout(() => navigate('/login'), 1000);
      return () => clearTimeout(timer);
    }
  }, [isAuthenticated, isLoading, error, navigate]);

  // Show Auth0 ID conflict error
  if (authConflictError) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-background">
        <div className="max-w-md w-full mx-4 p-6 bg-card border border-border rounded-lg shadow-lg">
          <div className="flex items-center space-x-3 mb-4">
            <AlertTriangle className="h-8 w-8 text-destructive" />
            <h1 className="text-xl font-semibold text-foreground">Account Conflict</h1>
          </div>

          <div className="space-y-4">
            <p className="text-muted-foreground">
              This email is already associated with a different Auth0 account. Please try a different sign-in method or contact support.
            </p>

            <div className="bg-muted p-4 rounded-md">
              <h2 className="font-medium text-foreground mb-2 flex items-center">
                <HelpCircle className="h-4 w-4 mr-2" />
                What happened?
              </h2>
              <p className="text-sm text-muted-foreground">
                You previously signed up using a different authentication method (Google, GitHub, or email/password).
              </p>
            </div>

            <div className="bg-muted p-4 rounded-md">
              <h2 className="font-medium text-foreground mb-2 flex items-center">
                <Mail className="h-4 w-4 mr-2" />
                Next steps
              </h2>
              <ul className="text-sm text-muted-foreground space-y-1">
                <li>• Try a different sign-in method</li>
                <li>• Contact support to merge accounts</li>
                <li>• Use a different email address</li>
              </ul>
            </div>

            <div className="flex space-x-3">
              <button
                onClick={handleLogout}
                className="flex-1 bg-primary text-primary-foreground px-4 py-2 rounded-md hover:bg-primary/90 transition-colors"
              >
                Try Different Login
              </button>
              <button
                onClick={() => window.open('mailto:support@contextd.local?subject=Auth0 Account Conflict', '_blank')}
                className="flex-1 bg-secondary text-secondary-foreground px-4 py-2 rounded-md hover:bg-secondary/90 transition-colors"
              >
                Contact Support
              </button>
            </div>

            {process.env.NODE_ENV === 'development' && (
              <details className="mt-4">
                <summary className="text-xs text-muted-foreground cursor-pointer">
                  Debug Information (Development Only)
                </summary>
                <pre className="text-xs text-muted-foreground mt-2 bg-background p-2 rounded border overflow-x-auto">
                  {JSON.stringify({
                    existingAuth0Id: authConflictError.existingAuth0Id,
                    incomingAuth0Id: authConflictError.incomingAuth0Id,
                    userEmail: user?.email,
                  }, null, 2)}
                </pre>
              </details>
            )}
          </div>
        </div>
      </div>
    );
  }

  // Loading state is the only visible UI for normal flow
  return (
    <div className="flex h-screen w-full items-center justify-center bg-background">
      <div className="flex flex-col items-center justify-center space-y-4">
        <Loader2 className="h-10 w-10 animate-spin text-primary" />
        {organizationName ? (
          <p className="text-muted-foreground">
            Finalizing your membership for {organizationName}...
          </p>
        ) : (
          <p className="text-muted-foreground">Finalizing authentication...</p>
        )}
      </div>
    </div>
  );
};

export default Callback;
