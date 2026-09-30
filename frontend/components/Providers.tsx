'use client';

import { ReactNode, useEffect } from 'react';
import { ErrorBoundary } from './ErrorBoundary';
import { useAppStore } from '@/lib/store';

interface ProvidersProps {
  children: ReactNode;
}

/**
 * Loads the colour theme of the current subject, on every page and whenever the subject
 * changes (including when the remembered subject is restored after a reload).
 */
function SubjectThemeLoader() {
  const currentSubject = useAppStore((state) => state.currentSubject);
  const loadSubjectTheme = useAppStore((state) => state.loadSubjectTheme);

  useEffect(() => {
    void loadSubjectTheme(currentSubject);
  }, [currentSubject, loadSubjectTheme]);

  return null;
}

/**
 * Client-side providers wrapper.
 *
 * Wraps the app with:
 * - Error Boundary for graceful error handling
 * - The subject theme loader
 */
export function Providers({ children }: ProvidersProps) {
  return (
    <ErrorBoundary>
      <SubjectThemeLoader />
      {children}
    </ErrorBoundary>
  );
}

export default Providers;
