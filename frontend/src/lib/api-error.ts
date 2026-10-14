export interface ApiErrorEnvelope {
  error?: {
    code?: string;
    message?: string;
    details?: unknown;
    request_id?: string;
  };
  detail?: unknown;
  errors?: unknown;
  message?: unknown;
}

export class ApiError extends Error {
  status: number;
  code?: string;
  details?: unknown;
  requestId?: string;
  payload?: unknown;

  constructor(
    message: string,
    options: {
      status: number;
      code?: string;
      details?: unknown;
      requestId?: string;
      payload?: unknown;
    }
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = options.status;
    this.code = options.code;
    this.details = options.details;
    this.requestId = options.requestId;
    this.payload = options.payload;
  }
}

const isRecord = (value: unknown): value is Record<string, unknown> => {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
};

const messageFromUnknown = (value: unknown): string | undefined => {
  if (typeof value === 'string' && value.trim()) {
    return value;
  }
  if (isRecord(value)) {
    for (const key of ['message', 'detail', 'error']) {
      const nested = value[key];
      if (typeof nested === 'string' && nested.trim()) {
        return nested;
      }
    }
  }
  return undefined;
};

export const getApiErrorMessage = (
  payload: unknown,
  fallback = 'Request failed'
): string => {
  if (typeof payload === 'string') {
    return payload || fallback;
  }
  if (!isRecord(payload)) {
    return fallback;
  }

  const envelope = payload as ApiErrorEnvelope;
  const envelopeMessage = messageFromUnknown(envelope.error);
  if (envelopeMessage) {
    return envelopeMessage;
  }

  const detailMessage = messageFromUnknown(envelope.detail);
  if (detailMessage) {
    return detailMessage;
  }

  const rootMessage = messageFromUnknown(envelope.message);
  if (rootMessage) {
    return rootMessage;
  }

  if (envelope.errors) {
    return 'Request validation failed';
  }

  return fallback;
};

const parseApiErrorPayload = async (response: Response): Promise<unknown> => {
  const responseClone = response.clone();
  const contentType = responseClone.headers.get('content-type') || '';

  if (contentType.includes('application/json')) {
    try {
      return await responseClone.json();
    } catch {
      return undefined;
    }
  }

  try {
    const text = await responseClone.text();
    return text || undefined;
  } catch {
    return undefined;
  }
};

export const createApiError = async (
  response: Response,
  fallback = `Request failed with status ${response.status}`
): Promise<ApiError> => {
  const payload = await parseApiErrorPayload(response);
  const envelope = isRecord(payload) ? (payload as ApiErrorEnvelope) : undefined;
  const error = envelope?.error;

  return new ApiError(getApiErrorMessage(payload, fallback), {
    status: response.status,
    code: error?.code,
    details: error?.details ?? envelope?.detail,
    requestId: error?.request_id,
    payload,
  });
};

export const ensureOk = async (
  response: Response,
  fallback?: string
): Promise<Response> => {
  if (!response.ok) {
    throw await createApiError(response, fallback);
  }
  return response;
};
