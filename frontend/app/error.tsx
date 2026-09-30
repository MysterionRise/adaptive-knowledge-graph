'use client'; // Error boundaries must be Client Components

import Link from 'next/link';
import { AlertTriangle, RotateCcw } from 'lucide-react';

interface ErrorPageProps {
  error: Error & { digest?: string };
  /** Re-fetches and re-renders the page segment. */
  retry: () => void;
}

/**
 * Shown instead of a page that crashed while rendering. The navigation bar stays usable.
 */
export default function ErrorPage({ error, retry }: ErrorPageProps) {
  return (
    <main
      id="main-content"
      className="flex min-h-[60vh] items-center justify-center bg-gray-50 px-4 py-16"
    >
      <div
        role="alert"
        className="w-full max-w-md rounded-lg border border-gray-200 bg-white p-8 text-center shadow-md"
      >
        <AlertTriangle className="mx-auto mb-4 h-10 w-10 text-red-500" aria-hidden="true" />
        <h1 className="mb-2 text-2xl font-bold text-gray-900">Something went wrong</h1>
        <p className="mb-6 text-gray-600">
          This page ran into an unexpected error. Try again, or go back to the home page.
        </p>
        {process.env.NODE_ENV === 'development' && (
          <p className="mb-6 break-all rounded-md bg-red-50 p-3 text-left font-mono text-sm text-red-700">
            {error.message}
          </p>
        )}
        <div className="flex justify-center gap-3">
          <button
            type="button"
            onClick={() => retry()}
            className="inline-flex items-center gap-2 rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700"
          >
            <RotateCcw className="h-4 w-4" aria-hidden="true" />
            Try again
          </button>
          <Link
            href="/"
            className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50"
          >
            Go to the home page
          </Link>
        </div>
      </div>
    </main>
  );
}
