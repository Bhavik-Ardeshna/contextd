/// <reference types="vite/client" />

interface Window {
  ENV?: {
    API_URL: string;
    LOCAL_DEVELOPMENT?: boolean;
    AUTH_ENABLED?: boolean;
    AUTH0_DOMAIN?: string;
    AUTH0_CLIENT_ID?: string;
    AUTH0_AUDIENCE?: string;
    DISABLE_AUTH?: boolean;
    ANALYTICS_ENABLED?: boolean;
    POSTHOG_API_KEY?: string;
    POSTHOG_HOST?: string;
  };
}
