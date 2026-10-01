import {
  ApiError,
  describeError,
  extractErrorDetail,
  isAbortError,
  messageForStatus,
  timeoutMessage,
} from '@/lib/api-errors';

describe('extractErrorDetail', () => {
  it('reads a string detail', () => {
    expect(extractErrorDetail({ detail: 'Subject not found' })).toBe('Subject not found');
  });

  it('joins validation errors with their field names', () => {
    expect(
      extractErrorDetail({
        detail: [
          { loc: ['query', 'topic'], msg: 'String should have at least 1 character', type: 'string_too_short' },
          { loc: ['body'], msg: 'Field required', type: 'missing' },
        ],
      })
    ).toBe('topic: String should have at least 1 character; Field required');
  });

  it('parses JSON sent as a string', () => {
    expect(extractErrorDetail('{"detail":"LLM service temporarily unavailable"}')).toBe(
      'LLM service temporarily unavailable'
    );
  });

  it('keeps short plain-text bodies', () => {
    expect(extractErrorDetail('  Bad gateway  ')).toBe('Bad gateway');
  });

  it.each([
    ['an HTML error page', '<html><body>502 Bad Gateway</body></html>'],
    ['a long text dump', 'x'.repeat(301)],
    ['an empty body', ''],
    ['a body without detail', { error: 'nope' }],
    ['an empty detail', { detail: '   ' }],
    ['unusable validation errors', { detail: [{ loc: ['body'] }, 'oops'] }],
    ['null', null],
  ])('returns null for %s', (_label, body) => {
    expect(extractErrorDetail(body)).toBeNull();
  });
});

describe('messageForStatus', () => {
  it.each([
    [401, 'The API rejected the request (missing or invalid API key).'],
    [404, 'The requested data was not found.'],
    [429, 'Too many requests. Please wait a moment and try again.'],
    [503, 'The server could not complete the request (HTTP 503).'],
    [418, 'The request failed (HTTP 418).'],
  ])('describes HTTP %s', (status, message) => {
    expect(messageForStatus(status)).toBe(message);
  });
});

describe('timeoutMessage', () => {
  it('names the timeout in seconds', () => {
    expect(timeoutMessage(30_000)).toBe('The server did not respond within 30 seconds.');
    expect(timeoutMessage(undefined)).toBe('The server took too long to respond.');
  });
});

describe('describeError', () => {
  it('uses the message of an API error', () => {
    expect(describeError(new ApiError('http', 'Subject not found', { status: 404 }))).toBe(
      'Subject not found'
    );
  });

  it('does not show messages of unexpected errors', () => {
    expect(describeError(new TypeError('x is undefined'))).toBe(
      'Something went wrong. Please try again.'
    );
    expect(describeError('boom', 'Custom fallback')).toBe('Custom fallback');
  });
});

describe('isAbortError', () => {
  it('recognises cancelled requests', () => {
    expect(isAbortError(new ApiError('aborted', 'The request was cancelled.'))).toBe(true);
    expect(isAbortError(new DOMException('The operation was aborted.', 'AbortError'))).toBe(true);
  });

  it('ignores other errors', () => {
    expect(isAbortError(new ApiError('timeout', 'Too slow'))).toBe(false);
    expect(isAbortError(new Error('boom'))).toBe(false);
    expect(isAbortError(undefined)).toBe(false);
  });
});

describe('ApiError', () => {
  it('keeps the status, detail and cause', () => {
    const cause = new Error('original');
    const error = new ApiError('http', 'Not found', { status: 404, detail: 'Not found', cause });

    expect(error).toBeInstanceOf(Error);
    expect(error).toMatchObject({ name: 'ApiError', kind: 'http', status: 404, detail: 'Not found' });
    expect(error.cause).toBe(cause);
  });

  it('defaults status and detail to null', () => {
    expect(new ApiError('network', 'Offline')).toMatchObject({ status: null, detail: null });
  });
});
