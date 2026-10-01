import { act, renderHook, waitFor } from '@testing-library/react';
import { ApiError } from '@/lib/api-errors';
import { useApiQuery } from '@/lib/useApiQuery';

/** A load function whose calls can be resolved or rejected by the test. */
function controllableLoad<T>() {
  const calls: Array<{
    signal: AbortSignal;
    resolve: (value: T) => void;
    reject: (error: unknown) => void;
  }> = [];
  const load = jest.fn(
    (signal: AbortSignal) =>
      new Promise<T>((resolve, reject) => {
        calls.push({ signal, resolve, reject });
      })
  );
  return { load, calls };
}

describe('useApiQuery', () => {
  it('loads data for the key', async () => {
    const { load, calls } = controllableLoad<string>();
    const { result } = renderHook(() => useApiQuery('stats', load));

    expect(result.current).toMatchObject({ isLoading: true, data: undefined, error: null });

    await act(async () => calls[0].resolve('loaded'));

    expect(result.current).toMatchObject({ isLoading: false, data: 'loaded', error: null });
    expect(load).toHaveBeenCalledTimes(1);
  });

  it('reports a failed request', async () => {
    const error = new ApiError('http', 'Neo4j unavailable', { status: 503 });
    const { load, calls } = controllableLoad<string>();
    const { result } = renderHook(() => useApiQuery('stats', load));

    await act(async () => calls[0].reject(error));

    expect(result.current).toMatchObject({ isLoading: false, data: undefined, error });
  });

  it('reports a load function that throws synchronously', async () => {
    const error = new Error('bad request');
    const { result } = renderHook(() =>
      useApiQuery('stats', () => {
        throw error;
      })
    );

    await waitFor(() => expect(result.current.error).toBe(error));
    expect(result.current.isLoading).toBe(false);
  });

  it('loads again on retry', async () => {
    const { load, calls } = controllableLoad<string>();
    const { result } = renderHook(() => useApiQuery('stats', load));
    await act(async () => calls[0].reject(new Error('down')));

    act(() => result.current.retry());

    expect(result.current).toMatchObject({ isLoading: true, error: null });
    await act(async () => calls[1].resolve('back'));
    expect(result.current).toMatchObject({ isLoading: false, data: 'back', error: null });
  });

  it('aborts the previous request when the key changes and ignores its late response', async () => {
    const { load, calls } = controllableLoad<string>();
    const { result, rerender } = renderHook(({ key }) => useApiQuery(key, load), {
      initialProps: { key: 'graph:us_history' },
    });

    rerender({ key: 'graph:economics' });

    expect(calls[0].signal.aborted).toBe(true);
    expect(result.current.isLoading).toBe(true);

    await act(async () => {
      calls[0].resolve('us history graph');
      calls[1].resolve('economics graph');
    });
    expect(result.current.data).toBe('economics graph');
  });

  it('keeps the previous data while a new key loads', async () => {
    const { load, calls } = controllableLoad<string>();
    const { result, rerender } = renderHook(({ key }) => useApiQuery(key, load), {
      initialProps: { key: 'a' },
    });
    await act(async () => calls[0].resolve('first'));

    rerender({ key: 'b' });

    expect(result.current).toMatchObject({ isLoading: true, data: 'first' });
  });

  it('ignores aborted requests', async () => {
    const { load, calls } = controllableLoad<string>();
    const { result } = renderHook(() => useApiQuery('stats', load));

    await act(async () => calls[0].reject(new ApiError('aborted', 'The request was cancelled.')));

    expect(result.current).toMatchObject({ isLoading: true, error: null });
  });

  it('aborts the request on unmount', () => {
    const { load, calls } = controllableLoad<string>();
    const { unmount } = renderHook(() => useApiQuery('stats', load));

    unmount();

    expect(calls[0].signal.aborted).toBe(true);
  });

  it('does not load without a key', () => {
    const load = jest.fn();
    const { result } = renderHook(() => useApiQuery(null, load));

    expect(load).not.toHaveBeenCalled();
    expect(result.current.isLoading).toBe(false);
  });

  it('uses the latest load function', async () => {
    const first = jest.fn(async () => 'first');
    const second = jest.fn(async () => 'second');
    const { result, rerender } = renderHook(({ load }) => useApiQuery('same-key', load), {
      initialProps: { load: first },
    });
    await waitFor(() => expect(result.current.data).toBe('first'));

    rerender({ load: second });
    // A new function with the same key does not reload...
    expect(second).not.toHaveBeenCalled();
    // ...but a retry uses it.
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.data).toBe('second'));
  });
});
