import type { Metadata } from 'next';
import Link from 'next/link';
import { Compass } from 'lucide-react';

export const metadata: Metadata = {
  title: 'Page not found',
};

export default function NotFound() {
  return (
    <main
      id="main-content"
      className="flex min-h-[60vh] items-center justify-center bg-gray-50 px-4 py-16"
    >
      <div className="w-full max-w-md rounded-lg border border-gray-200 bg-white p-8 text-center shadow-md">
        <Compass className="mx-auto mb-4 h-10 w-10 text-primary-600" aria-hidden="true" />
        <h1 className="mb-2 text-2xl font-bold text-gray-900">Page not found</h1>
        <p className="mb-6 text-gray-600">
          There is no page at this address. It may have moved, or the link may be mistyped.
        </p>
        <Link
          href="/"
          className="inline-flex rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700"
        >
          Go to the home page
        </Link>
      </div>
    </main>
  );
}
