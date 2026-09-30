/**
 * The error type thrown by the API client, plus helpers for showing it to users.
 *
 * Kept separate from `api-client.ts` so components (and tests that mock the client) can use the
 * helpers without loading axios.
 */

export type ApiErrorKind =
  /** The server answered with a non-2xx status. */
  | 'http'
  /** An answer stream reported an error event (the HTTP status was 200). */
  | 'stream'
  /** No response: the server is down or unreachable. */
  | 'network'
  /** The server did not answer within the request's timeout. */
  | 'timeout'
  /** The caller cancelled the request (AbortSignal). */
  | 'aborted';

interface ApiErrorOptions {
  status?: number | null;
  detail?: string | null;
  cause?: unknown;
}

/**
 * Every failed API request rejects with an `ApiError`. Its `message` is ready to show to users:
 * the backend's `detail` when the response had one, otherwise a short description of the failure.
 */
export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  /** HTTP status code, when the server responded. */
  readonly status: number | null;
  /** The backend's `detail` message, when the response carried one. */
  readonly detail: string | null;

  constructor(kind: ApiErrorKind, message: string, options: ApiErrorOptions = {}) {
    super(message, options.cause === undefined ? undefined : { cause: options.cause });
    this.name = 'ApiError';
    this.kind = kind;
    this.status = options.status ?? null;
    this.detail = options.detail ?? null;
  }
}

const GENERIC_ERROR = 'Something went wrong. Please try again.';
const MAX_PLAIN_TEXT_DETAIL = 300;

/** True when the error only means that the request was cancelled (nothing to show). */
export function isAbortError(error: unknown): boolean {
  if (error instanceof ApiError) return error.kind === 'aborted';
  // DOMException is not an Error subclass in every environment
  return typeof error === 'object' && error !== null && (error as Error).name === 'AbortError';
}

/** A message for users: the API error's message, or `fallback` for unexpected errors. */
export function describeError(error: unknown, fallback: string = GENERIC_ERROR): string {
  return error instanceof ApiError ? error.message : fallback;
}

function formatValidationIssue(issue: unknown): string | null {
  if (!issue || typeof issue !== 'object') return null;
  const { loc, msg } = issue as { loc?: unknown; msg?: unknown };
  if (typeof msg !== 'string' || !msg.trim()) return null;
  // Pydantic prefixes custom validator messages with "Value error, ".
  const message = msg.replace(/^Value error,\s*/i, '');
  const field = Array.isArray(loc)
    ? loc.filter((part) => !['body', 'query', 'path'].includes(String(part))).join('.')
    : '';
  return field ? `${field}: ${message}` : message;
}

/**
 * Extract the human-readable `detail` of a FastAPI error body.
 *
 * Handles `{detail: "..."}`, validation errors (`{detail: [{loc, msg, type}]}`), JSON sent as a
 * string, and short plain-text bodies. Returns null when there is nothing useful to show.
 */
export function extractErrorDetail(body: unknown): string | null {
  if (typeof body === 'string') {
    const text = body.trim();
    if (!text) return null;
    try {
      return extractErrorDetail(JSON.parse(text));
    } catch {
      // Not JSON. Ignore HTML error pages (e.g. from a proxy) and long dumps.
      return text.startsWith('<') || text.length > MAX_PLAIN_TEXT_DETAIL ? null : text;
    }
  }
  if (!body || typeof body !== 'object' || !('detail' in body)) return null;
  const { detail } = body as { detail: unknown };
  if (typeof detail === 'string') return detail.trim() || null;
  if (Array.isArray(detail)) {
    const messages = detail.map(formatValidationIssue).filter((m): m is string => m !== null);
    return messages.length > 0 ? messages.join('; ') : null;
  }
  return null;
}

/** Message for an HTTP error response without a usable `detail`. */
export function messageForStatus(status: number): string {
  if (status === 401 || status === 403) return 'The API rejected the request (missing or invalid API key).';
  if (status === 404) return 'The requested data was not found.';
  if (status === 429) return 'Too many requests. Please wait a moment and try again.';
  if (status >= 500) return `The server could not complete the request (HTTP ${status}).`;
  return `The request failed (HTTP ${status}).`;
}

export function networkErrorMessage(baseURL: string): string {
  return `Could not reach the API at ${baseURL}. Check that the backend is running.`;
}

export function timeoutMessage(timeoutMs: number | undefined): string {
  if (!timeoutMs) return 'The server took too long to respond.';
  return `The server did not respond within ${Math.round(timeoutMs / 1000)} seconds.`;
}

export const ABORTED_MESSAGE = 'The request was cancelled.';
