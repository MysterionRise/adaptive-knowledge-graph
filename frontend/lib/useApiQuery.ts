import { useCallback, useEffect, useEffectEvent, useState } from 'react';
import { isAbortError } from './api-errors';

export interface ApiQuery<T> {
  /** Data of the latest successful request (kept while a newer request is loading). */
  data: T | undefined;
  /** Error of the latest request, when it failed. */
  error: unknown;
  /** True while the request for the current key is in flight. */
  isLoading: boolean;
  /** Send the request again. */
  retry: () => void;
}

interface SettledRequest<T> {
  requestKey: string;
  data: T | undefined;
  error: unknown;
}

/**
 * Load data for `key`, and load it again when the key changes or `retry()` is called.
 *
 * The previous request is aborted whenever a new one starts (and on unmount), so a slow
 * response can never overwrite a newer one. `load` always sees the latest props; pass
 * `key: null` to skip loading.
 */
export function useApiQuery<T>(
  key: string | null,
  load: (signal: AbortSignal) => Promise<T>
): ApiQuery<T> {
  const [attempt, setAttempt] = useState(0);
  const [settled, setSettled] = useState<SettledRequest<T> | null>(null);
  const requestKey = key === null ? null : `${key}#${attempt}`;
  const runLoad = useEffectEvent(load);

  useEffect(() => {
    if (requestKey === null) return;
    const controller = new AbortController();
    new Promise<T>((resolve) => resolve(runLoad(controller.signal))).then(
      (data) => {
        if (!controller.signal.aborted) setSettled({ requestKey, data, error: null });
      },
      (error: unknown) => {
        if (controller.signal.aborted || isAbortError(error)) return;
        setSettled((previous) => ({ requestKey, data: previous?.data, error }));
      }
    );
    return () => controller.abort();
  }, [requestKey]);

  const retry = useCallback(() => setAttempt((count) => count + 1), []);

  const isCurrent = settled !== null && settled.requestKey === requestKey;
  return {
    data: settled?.data,
    error: isCurrent ? settled.error : null,
    isLoading: requestKey !== null && !isCurrent,
    retry,
  };
}
