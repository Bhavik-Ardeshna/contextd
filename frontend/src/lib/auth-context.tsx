import React, { createContext, useContext, useEffect, useState, useCallback, useMemo } from 'react';
import { useAuth0 } from '@auth0/auth0-react';
import authConfig from '../config/auth';
import { apiClient } from './api';
import { env } from '../config/env';

const DEV_AUTH_TOKEN_KEY = 'dev-auth-token';

interface AuthContextType {
  isAuthenticated: boolean;
  isLoading: boolean;
  user: any;
  login: () => void;
  logout: () => void;
  getToken: () => Promise<string | null>;
  clearToken: () => void;
  token: string | null;
  tokenInitialized: boolean;
  isReady: () => boolean;
  devLogin: (email: string, password: string) => Promise<{ success: boolean; error?: string }>;
  devRegister: (email: string, password: string, fullName?: string) => Promise<{ success: boolean; error?: string }>;
}

const AuthContext = createContext<AuthContextType>({
  isAuthenticated: false,
  isLoading: true,
  user: null,
  login: () => { },
  logout: () => { },
  getToken: async () => null,
  clearToken: () => { },
  token: null,
  tokenInitialized: false,
  isReady: () => false,
  devLogin: async () => ({ success: false }),
  devRegister: async () => ({ success: false }),
});

export const useAuth = () => useContext(AuthContext);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [token, setToken] = useState<string | null>(null);
  const [tokenInitialized, setTokenInitialized] = useState(false);
  const [enrichedUser, setEnrichedUser] = useState<any>(null);
  const [userProfileLoading, setUserProfileLoading] = useState(false);

  // Auth disabled state (bypass mode)
  const [authDisabledUser, setAuthDisabledUser] = useState<any>(null);
  const [authDisabledLoading, setAuthDisabledLoading] = useState(authConfig.authDisabled);

  // Dev auth state
  const [devAuthToken, setDevAuthToken] = useState<string | null>(() => {
    if (authConfig.devAuthEnabled) {
      return localStorage.getItem(DEV_AUTH_TOKEN_KEY);
    }
    return null;
  });
  const [devAuthUser, setDevAuthUser] = useState<any>(null);
  const [devAuthLoading, setDevAuthLoading] = useState(authConfig.devAuthEnabled);

  // Use Auth0 hooks if enabled, otherwise simulate with local state
  const {
    isAuthenticated: auth0IsAuthenticated,
    isLoading: auth0IsLoading,
    user: auth0User,
    loginWithRedirect,
    logout: auth0Logout,
    getAccessTokenSilently,
  } = useAuth0();

  // Determine authentication state based on mode
  const isAuthenticated = authConfig.authDisabled
    ? !!authDisabledUser
    : authConfig.devAuthEnabled
      ? !!devAuthToken
      : auth0IsAuthenticated;

  const isLoading = authConfig.authDisabled
    ? authDisabledLoading
    : authConfig.devAuthEnabled
      ? devAuthLoading
      : (auth0IsLoading || !tokenInitialized || userProfileLoading);

  const user = authConfig.authDisabled
    ? authDisabledUser
    : authConfig.devAuthEnabled
      ? devAuthUser
      : (enrichedUser || auth0User);

  // Auth disabled: auto-authenticate as system user on mount
  useEffect(() => {
    if (!authConfig.authDisabled) return;

    const fetchSystemUser = async () => {
      try {
        const response = await fetch(`${env.VITE_API_URL}/users/`, {
          headers: { 'Content-Type': 'application/json' },
        });

        if (response.ok) {
          const backendUser = await response.json();
          setAuthDisabledUser({
            name: backendUser.full_name || backendUser.email,
            email: backendUser.email,
            is_admin: backendUser.is_admin || false,
            id: backendUser.id,
          });
        }
      } catch {
        // Keep auth-disabled mode usable even if the system user cannot be fetched.
      } finally {
        setAuthDisabledLoading(false);
      }
    };

    fetchSystemUser();
  }, []);

  // Dev auth: validate existing token on mount
  useEffect(() => {
    if (!authConfig.devAuthEnabled) return;

    const validateDevToken = async () => {
      const storedToken = localStorage.getItem(DEV_AUTH_TOKEN_KEY);
      if (!storedToken) {
        setDevAuthLoading(false);
        return;
      }

      try {
        // Validate the token by fetching user profile
        const response = await fetch(`${env.VITE_API_URL}/users/`, {
          headers: {
            'Authorization': `Bearer ${storedToken}`,
            'Content-Type': 'application/json',
          },
        });

        if (response.ok) {
          const backendUser = await response.json();
          setDevAuthUser({
            name: backendUser.full_name || backendUser.email,
            email: backendUser.email,
            is_admin: backendUser.is_admin || false,
            id: backendUser.id,
          });
          setDevAuthToken(storedToken);
        } else {
          // Token is invalid, clear it
          localStorage.removeItem(DEV_AUTH_TOKEN_KEY);
          setDevAuthToken(null);
          setDevAuthUser(null);
        }
      } catch {
        localStorage.removeItem(DEV_AUTH_TOKEN_KEY);
        setDevAuthToken(null);
        setDevAuthUser(null);
      } finally {
        setDevAuthLoading(false);
      }
    };

    validateDevToken();
  }, []);

  // Dev auth login
  const devLogin = useCallback(async (email: string, password: string): Promise<{ success: boolean; error?: string }> => {
    try {
      const response = await fetch(`${env.VITE_API_URL}/dev-auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        return { success: false, error: errorData.detail || 'Login failed' };
      }

      const data = await response.json();
      localStorage.setItem(DEV_AUTH_TOKEN_KEY, data.access_token);
      setDevAuthToken(data.access_token);

      // Fetch user profile with the new token
      const userResponse = await fetch(`${env.VITE_API_URL}/users/`, {
        headers: {
          'Authorization': `Bearer ${data.access_token}`,
          'Content-Type': 'application/json',
        },
      });

      if (userResponse.ok) {
        const backendUser = await userResponse.json();
        setDevAuthUser({
          name: backendUser.full_name || backendUser.email,
          email: backendUser.email,
          is_admin: backendUser.is_admin || false,
          id: backendUser.id,
        });
      } else {
        setDevAuthUser({ name: 'User', email: data.email, is_admin: false, id: data.user_id });
      }

      return { success: true };
    } catch {
      return { success: false, error: 'Network error' };
    }
  }, []);

  // Dev auth register
  const devRegister = useCallback(async (email: string, password: string, fullName?: string): Promise<{ success: boolean; error?: string }> => {
    try {
      const response = await fetch(`${env.VITE_API_URL}/dev-auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password, full_name: fullName || 'User' }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        return { success: false, error: errorData.detail || 'Registration failed' };
      }

      const data = await response.json();
      localStorage.setItem(DEV_AUTH_TOKEN_KEY, data.access_token);
      setDevAuthToken(data.access_token);
      setDevAuthUser({ name: fullName || 'User', email: data.email, is_admin: false, id: data.user_id });

      return { success: true };
    } catch {
      return { success: false, error: 'Network error' };
    }
  }, []);

  // Get the token when authenticated (Auth0 mode)
  useEffect(() => {
    if (authConfig.devAuthEnabled) {
      // Dev auth manages its own state
      setTokenInitialized(true);
      return;
    }

    const getAccessToken = async () => {
      if (authConfig.authEnabled && auth0IsAuthenticated) {
        try {
          const accessToken = await getAccessTokenSilently();
          setToken(accessToken);
          setTokenInitialized(true);
        } catch {
          setToken(null);
          setTokenInitialized(true);
        }
      } else if (!auth0IsAuthenticated && !auth0IsLoading) {
        setTokenInitialized(true);
      }
    };

    getAccessToken();
  }, [auth0IsAuthenticated, auth0IsLoading, getAccessTokenSilently]);

  // Fetch user profile from backend after auth is complete
  useEffect(() => {
    if (authConfig.devAuthEnabled) return; // Dev auth handles its own user profile

    const fetchUserProfile = async () => {
      if (auth0IsAuthenticated && tokenInitialized && auth0User && !enrichedUser) {
        try {
          setUserProfileLoading(true);
          const response = await apiClient.get('/users/');

          if (response.ok) {
            const backendUser = await response.json();
            setEnrichedUser({
              ...auth0User,
              is_admin: backendUser.is_admin || false,
              id: backendUser.id,
            });
          } else {
            setEnrichedUser({
              ...auth0User,
              is_admin: false,
            });
          }
        } catch {
          setEnrichedUser({
            ...auth0User,
            is_admin: false,
          });
        } finally {
          setUserProfileLoading(false);
        }
      }
    };

    fetchUserProfile();
  }, [auth0IsAuthenticated, tokenInitialized, auth0User]);

  // Login function
  const login = useCallback(() => {
    if (authConfig.authEnabled) {
      loginWithRedirect();
    }
    // Dev auth login is handled separately via devLogin
  }, [loginWithRedirect]);

  // Logout function
  const logout = useCallback(() => {
    setToken(null);
    setEnrichedUser(null);

    if (authConfig.devAuthEnabled) {
      localStorage.removeItem(DEV_AUTH_TOKEN_KEY);
      setDevAuthToken(null);
      setDevAuthUser(null);
      return;
    }

    if (authConfig.authEnabled) {
      auth0Logout({
        logoutParams: {
          returnTo: window.location.origin
        }
      });
    }
  }, [auth0Logout]);

  // Clear token function
  const clearToken = useCallback(() => {
    setToken(null);
    if (authConfig.devAuthEnabled) {
      localStorage.removeItem(DEV_AUTH_TOKEN_KEY);
      setDevAuthToken(null);
    }
  }, []);

  // Get token function
  const getToken = useCallback(async (): Promise<string | null> => {
    if (authConfig.authDisabled) {
      return null; // No token needed — backend uses system user
    }

    if (authConfig.devAuthEnabled) {
      return localStorage.getItem(DEV_AUTH_TOKEN_KEY);
    }

    if (token) {
      return token;
    }

    if (auth0IsAuthenticated) {
      try {
        const newToken = await getAccessTokenSilently();
        setToken(newToken);
        return newToken;
      } catch {
        return null;
      }
    }

    return null;
  }, [devAuthToken, token, auth0IsAuthenticated, getAccessTokenSilently]);

  // Check if auth is ready
  const isReady = useCallback((): boolean => {
    if (authConfig.authDisabled) {
      return !authDisabledLoading;
    }
    if (authConfig.devAuthEnabled) {
      return !devAuthLoading;
    }
    return tokenInitialized && !auth0IsLoading;
  }, [auth0IsLoading, authDisabledLoading, devAuthLoading, tokenInitialized]);

  const contextValue = useMemo(
    () => ({
      isAuthenticated,
      isLoading,
      user,
      login,
      logout,
      getToken,
      clearToken,
      token: authConfig.authDisabled ? null : authConfig.devAuthEnabled ? devAuthToken : token,
      tokenInitialized: authConfig.authDisabled ? !authDisabledLoading : authConfig.devAuthEnabled ? !devAuthLoading : tokenInitialized,
      isReady,
      devLogin,
      devRegister,
    }),
    [
      clearToken,
      devAuthLoading,
      devAuthToken,
      devLogin,
      devRegister,
      getToken,
      isAuthenticated,
      isLoading,
      isReady,
      login,
      logout,
      token,
      tokenInitialized,
      user,
      authDisabledLoading,
    ]
  );

  return (
    <AuthContext.Provider value={contextValue}>
      {children}
    </AuthContext.Provider>
  );
};
