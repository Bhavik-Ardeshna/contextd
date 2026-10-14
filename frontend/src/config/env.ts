interface Env {
  VITE_API_URL: string;
  VITE_ACCESS_TOKEN?: string;
  VITE_LOCAL_DEVELOPMENT: boolean;
  VITE_ENABLE_AUTH?: string;
  VITE_DISABLE_AUTH: boolean;
  VITE_ANALYTICS_ENABLED: boolean;
  VITE_POSTHOG_API_KEY: string;
  VITE_POSTHOG_HOST: string;
}

// Normalize API URL: trim and ensure no trailing slash so path concatenation is safe
const rawApiUrl = window.ENV?.API_URL || import.meta.env.VITE_API_URL || 'http://localhost:8001';
const normalizedApiUrl = (typeof rawApiUrl === 'string' ? rawApiUrl : '').trim().replace(/\/+$/, '') || 'http://localhost:8001';
const localSafeApiUrl =
  typeof window !== 'undefined' &&
  window.location.hostname === 'localhost' &&
  normalizedApiUrl === 'http://localhost:8001'
    ? 'http://127.0.0.1:8001'
    : normalizedApiUrl;
const rawPostHogHost = window.ENV?.POSTHOG_HOST || import.meta.env.VITE_POSTHOG_HOST || 'https://eu.i.posthog.com';
const analyticsEnabled = window.ENV?.ANALYTICS_ENABLED ?? import.meta.env.VITE_ANALYTICS_ENABLED === 'true';

export const env: Env = {
  // Use runtime config if available, otherwise fall back to Vite env vars
  VITE_API_URL: localSafeApiUrl,
  VITE_ACCESS_TOKEN: import.meta.env.VITE_ACCESS_TOKEN || '',
  VITE_LOCAL_DEVELOPMENT: window.ENV?.LOCAL_DEVELOPMENT ||
    import.meta.env.VITE_LOCAL_DEVELOPMENT === 'true' ||
    (import.meta.env.MODE === 'development'),
  VITE_ENABLE_AUTH: String(window.ENV?.AUTH_ENABLED ?? import.meta.env.VITE_ENABLE_AUTH ?? 'true'),
  VITE_DISABLE_AUTH: (window.ENV?.DISABLE_AUTH === true) ||
    (import.meta.env.VITE_DISABLE_AUTH === 'true') ||
    false,
  VITE_ANALYTICS_ENABLED: analyticsEnabled,
  VITE_POSTHOG_API_KEY: window.ENV?.POSTHOG_API_KEY || import.meta.env.VITE_POSTHOG_API_KEY || '',
  VITE_POSTHOG_HOST: (typeof rawPostHogHost === 'string' ? rawPostHogHost : '').trim(),
};
