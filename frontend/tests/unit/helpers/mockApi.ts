/**
 * Hermetic backend for unit tests.
 *
 * `MockApi.adapter` is an axios adapter that answers API requests by "<METHOD> <path>" (the same
 * routing as the Playwright fixtures), so tests run the real API client (URLs, query parameters,
 * timeouts, error handling) without a network. Requests without a handler are recorded in
 * `unexpected` and fail; a pending request rejects when its AbortSignal aborts.
 *
 * Components use the `apiClient` singleton, so a test swaps it for one backed by `mockApi`:
 *
 *   jest.mock('@/lib/api-client', () => {
 *     const actual = jest.requireActual('@/lib/api-client');
 *     return {
 *       ...actual,
 *       __esModule: true,
 *       apiClient: new actual.default('http://localhost:8000', {
 *         adapter: (config: unknown) => require('./helpers/mockApi').mockApi.adapter(config),
 *       }),
 *     };
 *   });
 */
import axios, {
  AxiosError,
  type AxiosAdapter,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from 'axios';

export interface MockApiRequest {
  method: string;
  /** Path without the query string, e.g. "/api/v1/quiz/generate". */
  path: string;
  params: URLSearchParams;
  /** Parsed JSON body (null without a body). */
  body: unknown;
  config: InternalAxiosRequestConfig;
}

export interface MockApiReply {
  status?: number;
  data?: unknown;
}

export type MockApiHandler = (request: MockApiRequest) => MockApiReply | Promise<MockApiReply>;

/** A JSON reply. */
export const json = (data: unknown, status = 200): MockApiReply => ({ status, data });

/** A reply that never arrives (until the request is aborted). */
export const pending = (): Promise<MockApiReply> => new Promise<MockApiReply>(() => {});

const parseBody = (data: unknown): unknown => {
  if (typeof data !== 'string' || data === '') return data ?? null;
  try {
    return JSON.parse(data);
  } catch {
    return data;
  }
};

export class MockApi {
  private handlers: Record<string, MockApiHandler> = {};
  readonly requests: MockApiRequest[] = [];
  readonly unexpected: string[] = [];

  /** Answer "<METHOD> <path>" with a handler or a fixed reply (replaces a previous one). */
  on(route: string, reply: MockApiHandler | MockApiReply): this {
    this.handlers[route] = typeof reply === 'function' ? reply : () => reply;
    return this;
  }

  /** Forget all handlers and recorded requests. */
  reset(): void {
    this.handlers = {};
    this.requests.length = 0;
    this.unexpected.length = 0;
  }

  /** Requests sent to "<METHOD> <path>". */
  calls(route: string): MockApiRequest[] {
    return this.requests.filter((request) => `${request.method} ${request.path}` === route);
  }

  readonly adapter: AxiosAdapter = (config) => {
    const url = new URL(axios.getUri(config));
    const request: MockApiRequest = {
      method: (config.method ?? 'get').toUpperCase(),
      path: url.pathname,
      params: url.searchParams,
      body: parseBody(config.data),
      config,
    };
    this.requests.push(request);

    const route = `${request.method} ${request.path}`;
    const handler = this.handlers[route];
    if (!handler) {
      this.unexpected.push(route);
      return Promise.reject(new Error(`Unexpected request in a unit test: ${route}`));
    }

    const signal = config.signal as AbortSignal | undefined;
    return new Promise<AxiosResponse>((resolve, reject) => {
      const cancel = () => reject(new axios.CanceledError(undefined, undefined, config));
      if (signal?.aborted) {
        cancel();
        return;
      }
      signal?.addEventListener?.('abort', cancel, { once: true });

      Promise.resolve()
        .then(() => handler(request))
        .then(({ status = 200, data = null }) => {
          const response: AxiosResponse = {
            data,
            status,
            statusText: String(status),
            headers: {},
            config,
            request: {},
          };
          if (status >= 400) {
            const code = status >= 500 ? AxiosError.ERR_BAD_RESPONSE : AxiosError.ERR_BAD_REQUEST;
            reject(new AxiosError(`Request failed with status code ${status}`, code, config, {}, response));
          } else {
            resolve(response);
          }
        }, reject)
        .finally(() => signal?.removeEventListener?.('abort', cancel));
    });
  };
}

/** Shared instance for the `apiClient` swapped in by `jest.mock` (see the module comment). */
export const mockApi = new MockApi();
