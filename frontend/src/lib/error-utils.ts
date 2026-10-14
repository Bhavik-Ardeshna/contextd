/**
 * error-utils.ts
 *
 * Utility functions for handling connection errors consistently across the application.
 * Uses localStorage to store error details and URL parameter just for signaling.
 */

import { NavigateFunction } from "react-router-dom";
import { protectedPaths } from "@/constants/paths";

// Storage key for error data
export const CONNECTION_ERROR_STORAGE_KEY = "contextd_connection_error";

/**
 * ErrorDetails interface
 * Defines the structure of error information stored in localStorage
 */
export interface ErrorDetails {
    serviceName?: string;
    sourceShortName?: string;    // Add source short name for proper image display
    errorMessage: string;
    errorDetails?: string;
    timestamp: number;
    canRetry?: boolean;     // Whether this error can be retried
    dialogState?: any;      // Store dialog state for potential retry
    dialogId?: string;      // Identify which dialog should handle the error
}

const SENSITIVE_ERROR_FIELD = /(authvalues|authorization|password|secret|token|api[_-]?key|access|refresh|credential|code)/i;

const sanitizeForStorage = (value: unknown, key?: string): unknown => {
    if (key && SENSITIVE_ERROR_FIELD.test(key)) {
        return "[redacted]";
    }

    if (Array.isArray(value)) {
        return value.map((item) => sanitizeForStorage(item));
    }

    if (value && typeof value === "object") {
        return Object.fromEntries(
            Object.entries(value as Record<string, unknown>).map(([entryKey, entryValue]) => [
                entryKey,
                sanitizeForStorage(entryValue, entryKey),
            ])
        );
    }

    return value;
};

const sanitizeErrorDetails = (errorData: ErrorDetails): ErrorDetails => ({
    ...errorData,
    errorDetails: undefined,
    dialogState: errorData.dialogState
        ? sanitizeForStorage(errorData.dialogState, "dialogState")
        : undefined,
});

/**
 * Stores error details in localStorage and redirects to dashboard
 *
 * @param navigate - React Router navigate function or window.location
 * @param error - Error object or message
 * @param serviceName - Name of the service that failed (optional)
 */
export const redirectWithError = (
    navigateOrLocation: NavigateFunction | typeof window.location | Location,
    error: Error | string | ErrorDetails,
    serviceName?: string
) => {
    // Extract error information
    let errorData: ErrorDetails;

    if (typeof error === 'string') {
        errorData = {
            serviceName,
            errorMessage: error,
            errorDetails: error,
            timestamp: Date.now()
        };
    } else if (error instanceof Error) {
        errorData = {
            serviceName,
            errorMessage: error.message || "Connection failed",
            errorDetails: undefined,
            timestamp: Date.now()
        };
    } else {
        // It's already an ErrorDetails object
        errorData = {
            ...error,
            serviceName: error.serviceName || serviceName,
            timestamp: Date.now()
        };
    }

    const safeErrorData = sanitizeErrorDetails(errorData);

    // Store in localStorage with more reliable stringify
    try {
        localStorage.setItem(CONNECTION_ERROR_STORAGE_KEY, JSON.stringify(safeErrorData));
    } catch {
        // Ignore storage failures; navigation still carries the generic error flag.
    }

    // Create URL with just the error flag (no sensitive data)
    const targetUrl = `${protectedPaths.dashboard}?connected=error`;

    // Use appropriate navigation method based on type
    if (typeof navigateOrLocation === 'function') {
        // React Router navigate function
        navigateOrLocation(targetUrl, { replace: true });
    } else {
        // Window.location or Location object
        try {
            // Check if it's window.location (has href property)
            if ('href' in navigateOrLocation) {
                navigateOrLocation.href = targetUrl;
            } else {
                // Fallback to window.location
                window.location.href = targetUrl;
            }
        } catch {
            // Absolute fallback
            window.location.href = targetUrl;
        }
    }
};

/**
 * Stores error details in localStorage and redirects to dashboard
 *
 * @param error - Error object or message
 * @param serviceName - Name of the service that failed (optional)
 */
export const storeErrorDetails = (error: ErrorDetails) => {
    try {
        localStorage.setItem(CONNECTION_ERROR_STORAGE_KEY, JSON.stringify(sanitizeErrorDetails({
            ...error,
            timestamp: Date.now()
        })));
    } catch {
        // Ignore storage failures; callers still show their immediate error UI.
    }
};

/**
 * Retrieves error details from localStorage
 *
 * @returns Error details or null if none found
 */
export const getStoredErrorDetails = (): ErrorDetails | null => {
    try {
        const rawData = localStorage.getItem(CONNECTION_ERROR_STORAGE_KEY);

        if (!rawData) {
            return null;
        }

        const data = JSON.parse(rawData);
        return data;
    } catch {
        return null;
    }
};

/**
 * Clears error details from localStorage
 */
export const clearStoredErrorDetails = () => {
    try {
        localStorage.removeItem(CONNECTION_ERROR_STORAGE_KEY);
    } catch {
        // Ignore storage failures during cleanup.
    }
};
