/**
 * PostHog Analytics Provider
 *
 * SECURITY NOTE: Using npm package instead of CDN for CASA-6 compliance
 * (no untrusted external scripts).
 *
 * INITIALIZATION STRATEGY:
 * - Initializes outside React component to avoid race conditions
 * - Manual pageview capture to ensure session is created before API calls
 * - Session recording enabled for debugging (with input masking)
 *
 * USAGE:
 * - Wrap your app with <PostHogProvider> in main.tsx
 * - Analytics is opt-in via runtime/Vite config
 * - Use exported helpers for custom tracking and session access
 */

import { env } from '@/config/env';
import posthog from 'posthog-js';
import { PostHogProvider as PHProvider } from 'posthog-js/react';

type AnalyticsProperties = Record<string, unknown>;

const isAnalyticsEnabled = Boolean(env.VITE_ANALYTICS_ENABLED && env.VITE_POSTHOG_API_KEY);

// Initialize PostHog outside of React component to avoid race conditions
if (typeof window !== 'undefined' && isAnalyticsEnabled) {
    posthog.init(env.VITE_POSTHOG_API_KEY, {
        api_host: env.VITE_POSTHOG_HOST,
        person_profiles: 'always',
        capture_pageview: false, // We'll capture manually to ensure session is created
        // Enable session recording for better debugging
        session_recording: {
            maskAllInputs: true,
            maskTextSelector: '[data-sensitive]',
        },
        // Respect user privacy
        opt_out_capturing_by_default: false,
        loaded: (client) => {
            // Capture initial pageview to ensure session is created
            client.capture('$pageview');
        },
    });
}

/**
 * PostHog Provider Component
 * Wraps the app to enable PostHog React hooks and automatic event tracking
 */
export function PostHogProvider({ children }: { children: React.ReactNode }) {
    if (!isAnalyticsEnabled) {
        return <>{children}</>;
    }

    return <PHProvider client={posthog}>{children}</PHProvider>;
}

export function captureAnalyticsEvent(eventName: string, properties?: AnalyticsProperties): void {
    if (!isAnalyticsEnabled) {
        return;
    }

    try {
        posthog.capture(eventName, properties);
    } catch {
        // Analytics must never affect product behavior.
    }
}

export function getPostHogSessionId(): string | undefined {
    if (!isAnalyticsEnabled || typeof posthog.get_session_id !== 'function') {
        return undefined;
    }

    try {
        return posthog.get_session_id();
    } catch {
        return undefined;
    }
}
