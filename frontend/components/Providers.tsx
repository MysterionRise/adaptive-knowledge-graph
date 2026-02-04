'use client';

import { ReactNode } from 'react';
import { ErrorBoundary } from './ErrorBoundary';

interface ProvidersProps {
  children: ReactNode;
}

/**
 * Client-side providers wrapper.
 *
 * Wraps the app with:
 * - Error Boundary for graceful error handling
 * - Future: Theme provider, auth context, etc.
 */
export function Providers({ children }: ProvidersProps) {
  return (
    <ErrorBoundary>
      {children}
    </ErrorBoundary>
  );
}

export default Providers;
