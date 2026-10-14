import { env } from '../config/env';
import { useOrganizationStore } from '@/lib/stores/organizations';
import { getPostHogSessionId } from '@/lib/posthog-provider';

export {
  ApiError,
  createApiError,
  ensureOk,
  getApiErrorMessage,
  type ApiErrorEnvelope,
} from '@/lib/api-error';

// Define a token provider interface
interface TokenProvider {
  getToken: () => Promise<string | null>;
  clearToken?: () => void;
  isReady?: () => boolean;
}

const DEV_AUTH_TOKEN_KEY = 'dev-auth-token';

const getStoredDevAuthToken = () => {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage.getItem(DEV_AUTH_TOKEN_KEY);
  } catch {
    return null;
  }
};

// Default implementation that uses env variable
const defaultTokenProvider: TokenProvider = {
  getToken: async () => env.VITE_ACCESS_TOKEN || getStoredDevAuthToken(),
  clearToken: () => {},
  isReady: () => Boolean(env.VITE_DISABLE_AUTH || env.VITE_ACCESS_TOKEN || getStoredDevAuthToken()),
};

// Current token provider instance
let tokenProvider: TokenProvider = defaultTokenProvider;

// Request queue system
interface QueuedRequest {
  execute: () => Promise<Response>;
  resolve: (value: Response) => void;
  reject: (reason: any) => void;
}

const requestQueue: QueuedRequest[] = [];
let isProcessingQueue = false;
let readinessCheckInterval: ReturnType<typeof setInterval> | null = null;
let readinessCheckTimeout: ReturnType<typeof setTimeout> | null = null;

// Function to set a custom token provider
export const setTokenProvider = (provider: TokenProvider) => {
  tokenProvider = provider;

  // Try to process any queued requests when provider changes
  processQueue();

  if (readinessCheckInterval) {
    clearInterval(readinessCheckInterval);
    readinessCheckInterval = null;
  }
  if (readinessCheckTimeout) {
    clearTimeout(readinessCheckTimeout);
    readinessCheckTimeout = null;
  }

  if (!provider.isReady || provider.isReady() || requestQueue.length === 0) {
    return;
  }

  // Set up a periodic check to process queue when auth becomes ready
  readinessCheckInterval = setInterval(() => {
    if (provider.isReady && provider.isReady() && requestQueue.length > 0) {
      processQueue();
      if (readinessCheckInterval) {
        clearInterval(readinessCheckInterval);
        readinessCheckInterval = null;
      }
    }
  }, 100);

  // Clear interval after 10 seconds to prevent memory leak
  readinessCheckTimeout = setTimeout(() => {
    if (readinessCheckInterval) {
      clearInterval(readinessCheckInterval);
      readinessCheckInterval = null;
    }
  }, 10000);
};

// Process the request queue
const processQueue = async () => {
  // If we're already processing or the queue is empty, do nothing
  if (isProcessingQueue || requestQueue.length === 0) {
    return;
  }

  // Check if auth is ready
  const isAuthReady = tokenProvider.isReady ? tokenProvider.isReady() : true;
  if (!isAuthReady) {
    // Auth not ready yet, try again later
    setTimeout(processQueue, 100);
    return;
  }

  isProcessingQueue = true;

  while (requestQueue.length > 0) {
    const request = requestQueue.shift();
    if (!request) continue;

    try {
      const response = await request.execute();
      request.resolve(response);
    } catch (error) {
      request.reject(error);
    }
  }

  isProcessingQueue = false;
};

// Helper to queue a request if auth is not ready
const queueOrExecute = async (requestFn: () => Promise<Response>): Promise<Response> => {
  const isAuthReady = tokenProvider.isReady ? tokenProvider.isReady() : true;

  if (isAuthReady) {
    return requestFn();
  }

  // Queue the request with a timeout to prevent permanent hangs
  return new Promise((resolve, reject) => {
    const queueEntry: QueuedRequest = {
      execute: requestFn,
      resolve: () => {},  // Will be replaced below
      reject: () => {},   // Will be replaced below
    };

    const timeoutId = setTimeout(() => {
      // Remove this request from the queue if it's still there
      const index = requestQueue.indexOf(queueEntry);
      if (index !== -1) {
        requestQueue.splice(index, 1);
      }
      reject(new Error('Request timed out waiting for authentication to be ready. Please refresh the page and try again.'));
    }, 30000); // 30 second timeout

    queueEntry.resolve = (value: Response) => {
      clearTimeout(timeoutId);
      resolve(value);
    };
    queueEntry.reject = (reason: any) => {
      clearTimeout(timeoutId);
      reject(reason);
    };

    requestQueue.push(queueEntry);
  });
};

export const API_CONFIG = {
  baseURL: env.VITE_API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
} as const;

type ApiResponse<T = any> = Promise<Response>;
type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

type ApiCachePolicy = {
  ttlMs: number;
};

type CachedApiResponse = {
  body: string;
  headers: Array<[string, string]>;
  status: number;
  statusText: string;
  storedAt: number;
};

type GetOptions = {
  signal?: AbortSignal;
  cache?: boolean;
};

const apiResponseCache = new Map<string, CachedApiResponse>();
const inflightGetRequests = new Map<string, Promise<CachedApiResponse>>();
const API_CACHE_MAX_ENTRIES = 160;

const responseFromCacheRecord = (record: CachedApiResponse): Response =>
  new Response(record.body, {
    status: record.status,
    statusText: record.statusText,
    headers: new Headers(record.headers),
  });

const isCacheRecordFresh = (record: CachedApiResponse, policy: ApiCachePolicy) =>
  Date.now() - record.storedAt <= policy.ttlMs;

const trimApiResponseCache = () => {
  if (apiResponseCache.size <= API_CACHE_MAX_ENTRIES) return;
  const entries = Array.from(apiResponseCache.entries()).sort((a, b) => a[1].storedAt - b[1].storedAt);
  const removeCount = Math.max(0, entries.length - API_CACHE_MAX_ENTRIES);
  entries.slice(0, removeCount).forEach(([key]) => apiResponseCache.delete(key));
};

export const clearApiResponseCache = (matcher?: (key: string) => boolean) => {
  if (!matcher) {
    apiResponseCache.clear();
    inflightGetRequests.clear();
    return;
  }

  Array.from(apiResponseCache.keys()).forEach((key) => {
    if (matcher(key)) apiResponseCache.delete(key);
  });
  Array.from(inflightGetRequests.keys()).forEach((key) => {
    if (matcher(key)) inflightGetRequests.delete(key);
  });
};

const getReadCachePolicy = (endpoint: string): ApiCachePolicy | null => {
  const [path] = endpoint.split('?');

  if (path === '/collections' || path === '/collections/count' || /^\/collections\/[^/]+$/.test(path)) {
    return { ttlMs: 12_000 };
  }

  if (path.startsWith('/source-connections')) {
    // Source status can change while a job runs, so keep this short while still
    // making tab/page transitions feel instant.
    return { ttlMs: 4_000 };
  }

  if (path.startsWith('/context-forge/databases')) {
    return { ttlMs: 8_000 };
  }

  if (path.startsWith('/context-intelligence/databases')) {
    return { ttlMs: 8_000 };
  }

  if (path.startsWith('/graph/organizations')) {
    return { ttlMs: 6_000 };
  }

  if (path === '/sources' || path.startsWith('/sources/')) {
    return { ttlMs: 60_000 };
  }

  return null;
};

const buildCacheKey = (url: URL, headers: Record<string, string>) => {
  const organizationId = headers['X-Organization-ID'] || '';
  const authFingerprint = headers.Authorization ? headers.Authorization.slice(-18) : 'anonymous';
  return `GET ${url.toString()} org:${organizationId} auth:${authFingerprint}`;
};

const materializeResponse = async (response: Response): Promise<CachedApiResponse> => ({
  body: await response.text(),
  headers: Array.from(response.headers.entries()),
  status: response.status,
  statusText: response.statusText,
  storedAt: Date.now(),
});

// Get headers with optional organization context
const getHeaders = async (): Promise<Record<string, string>> => {
  const providerToken = await tokenProvider.getToken();
  // During dev-auth login/route transitions the React provider can briefly hold
  // an older closure. The stored dev token is the authoritative local fallback.
  const token = providerToken || env.VITE_ACCESS_TOKEN || getStoredDevAuthToken();
  const { currentOrganization } = useOrganizationStore.getState();

  const headers: Record<string, string> = {
    ...API_CONFIG.headers,
    ...(token && { Authorization: `Bearer ${token}` }),
  };

  // Add organization context header if available
  if (currentOrganization) {
    headers['X-Organization-ID'] = currentOrganization.id;
  }

  // Add PostHog session ID if available
  const sessionId = getPostHogSessionId();
  if (sessionId) {
    headers['X-ContextD-Session-ID'] = sessionId;
  }

  return headers;
};

// Shared HTTP request function to eliminate duplication
const makeRequest = async <T>(
  method: HttpMethod,
  endpoint: string,
  options?: {
    data?: any;
    params?: Record<string, any>;
    signal?: AbortSignal;
    cache?: boolean;
  },
): ApiResponse<T> => {
  const requestFn = async () => {
    const url = new URL(`${API_CONFIG.baseURL}${endpoint}`);
    if (options?.params) {
      Object.entries(options.params).forEach(([key, value]) =>
        url.searchParams.append(key, String(value))
      );
    }

    let headers = await getHeaders();

    const fetchOptions: RequestInit = {
      method,
      headers,
      signal: options?.signal,
    };

    // Add body for methods that support it
    if (options?.data && method !== 'GET' && method !== 'DELETE') {
      fetchOptions.body = JSON.stringify(options.data);
    }

    const cachePolicy =
      method === 'GET' && options?.cache !== false && !options?.signal ? getReadCachePolicy(endpoint) : null;
    const cacheKey = cachePolicy ? buildCacheKey(url, headers) : null;

    if (cachePolicy && cacheKey) {
      const cached = apiResponseCache.get(cacheKey);
      if (cached && isCacheRecordFresh(cached, cachePolicy)) {
        return responseFromCacheRecord(cached);
      }

      const inflight = inflightGetRequests.get(cacheKey);
      if (inflight) {
        return responseFromCacheRecord(await inflight);
      }

      const networkRequest = (async () => {
        let response = await fetch(url.toString(), fetchOptions);

        if (response.status === 401 || response.status === 403) {
          const failedWithAuthorization = Boolean(headers.Authorization);
          if (failedWithAuthorization && tokenProvider.clearToken) {
            tokenProvider.clearToken();
          }

          headers = await getHeaders();

          if (headers.Authorization) {
            fetchOptions.headers = headers;
            response = await fetch(url.toString(), fetchOptions);
          }
        }

        const materialized = await materializeResponse(response);
        if (response.ok) {
          apiResponseCache.set(cacheKey, materialized);
          trimApiResponseCache();
        } else {
          apiResponseCache.delete(cacheKey);
        }
        return materialized;
      })();

      inflightGetRequests.set(cacheKey, networkRequest);
      try {
        return responseFromCacheRecord(await networkRequest);
      } finally {
        inflightGetRequests.delete(cacheKey);
      }
    }

    let response = await fetch(url.toString(), fetchOptions);

    // Handle 401/403 by attempting token refresh once
    if (response.status === 401 || response.status === 403) {
      const failedWithAuthorization = Boolean(headers.Authorization);
      if (failedWithAuthorization && tokenProvider.clearToken) {
        tokenProvider.clearToken(); // Clear the cached token only when it was actually used.
      }

      // Get fresh headers with new token
      headers = await getHeaders();

      if (headers.Authorization) {
        // Retry with new token
        fetchOptions.headers = headers;
        response = await fetch(url.toString(), fetchOptions);
      }
    }

    return response;
  };

  const response = await queueOrExecute(requestFn);
  if (method !== 'GET' && response.ok) {
    clearApiResponseCache();
  }
  return response;
};

// ---- SSE support (unified with the same baseURL, headers, and token-refresh) ----

type SSEHandlers = {
  onMessage: (msg: MessageEvent) => void;
  onOpen?: (res: Response) => void | Promise<void>;
  onError?: (err: any) => void;
  onClose?: () => void;
};

const waitForAuthReady = async () => {
  if (tokenProvider.isReady && !tokenProvider.isReady()) {
    await new Promise<void>((resolve) => {
      const started = Date.now();
      const interval = setInterval(() => {
        if (!tokenProvider.isReady || tokenProvider.isReady()) {
          clearInterval(interval);
          resolve();
        }
        // Hard cap to avoid dangling intervals
        if (Date.now() - started > 10_000) {
          clearInterval(interval);
          resolve();
        }
      }, 100);
    });
  }
};

export const apiClient = {
  clearToken: () => {
    if (tokenProvider.clearToken) {
      tokenProvider.clearToken();
    }
    clearApiResponseCache();
  },

  // Add getToken method to get current auth token
  getToken: async (): Promise<string | null> => {
    return tokenProvider.getToken();
  },

  async get<T>(endpoint: string, params?: Record<string, any>, options?: GetOptions): ApiResponse<T> {
    return makeRequest<T>('GET', endpoint, { params, signal: options?.signal, cache: options?.cache });
  },

  async post<T>(endpoint: string, data?: any, params?: Record<string, any>): ApiResponse<T> {
    // Accept either query params directly or request options with params/signal.
    const raw = params as any;
    const options = {
      data,
      params: raw && raw.params ? raw.params : (raw && !raw.signal ? raw : undefined),
      signal: raw && raw.signal ? raw.signal : undefined,
    } as { data?: any; params?: Record<string, any>; signal?: AbortSignal };
    return makeRequest<T>('POST', endpoint, options);
  },

  async put<T>(endpoint: string, params?: Record<string, any>, data?: any): ApiResponse<T> {
    return makeRequest<T>('PUT', endpoint, { data, params });
  },

  async patch<T>(endpoint: string, data?: any, params?: Record<string, any>): ApiResponse<T> {
    return makeRequest<T>('PATCH', endpoint, { data, params });
  },

  async delete<T>(endpoint: string, params?: Record<string, any>): ApiResponse<T> {
    return makeRequest<T>('DELETE', endpoint, { params });
  },

  // New: SSE method that uses the same baseURL + headers + token refresh semantics
  async sse(
    endpoint: string,
    handlers: SSEHandlers,
    options?: {
      params?: Record<string, any>;
      signal?: AbortSignal;
      method?: 'GET' | 'POST'; // usually GET for SSE
      openWhenHidden?: boolean;
    }
  ): Promise<void> {
    await waitForAuthReady();

    const url = new URL(`${API_CONFIG.baseURL}${endpoint}`);
    if (options?.params) {
      Object.entries(options.params).forEach(([k, v]) =>
        url.searchParams.append(k, String(v))
      );
    }

    const { fetchEventSource } = await import('@microsoft/fetch-event-source');

    // Bridge the caller's AbortSignal into our own so we can cleanly abort
    const controller = new AbortController();
    if (options?.signal) {
      options.signal.addEventListener('abort', () => controller.abort(), { once: true });
    }

    const initialHeaders = await getHeaders();

    return fetchEventSource(url.toString(), {
      method: options?.method ?? 'GET',
      signal: controller.signal,
      openWhenHidden: options?.openWhenHidden ?? true,

      // Initial headers (Authorization + X-Organization-ID)
      headers: initialHeaders,

      onopen: async (res) => {
        if (handlers.onOpen) await handlers.onOpen(res);
        if (res.status === 401 || res.status === 403) {
          // force a refresh on first unauthorized open, then let the library retry
          if (initialHeaders.Authorization) {
            tokenProvider.clearToken?.();
          }
          throw new Error('Unauthorized; retrying with refreshed token');
        }
        if (!res.ok) {
          throw new Error(`SSE failed with status ${res.status}`);
        }
      },

      onmessage: handlers.onMessage as any,

      onerror: (err) => {
        handlers.onError?.(err);
        // Throw to allow the library to decide retry/stop behavior
        throw err;
      },

      // Ensure each (re)connect uses fresh headers and one-shot token refresh
      fetch: async (input, init) => {
        let headers = await getHeaders();
        let res = await fetch(input, { ...init, headers });

        if (res.status === 401 || res.status === 403) {
          const failedWithAuthorization = Boolean(headers.Authorization);
          if (failedWithAuthorization && tokenProvider.clearToken) {
            tokenProvider.clearToken();
          }
          headers = await getHeaders();
          if (headers.Authorization) {
            res = await fetch(input, { ...init, headers });
          }
        }
        return res;
      },
    }).finally(() => {
      handlers.onClose?.();
    });
  },
};
