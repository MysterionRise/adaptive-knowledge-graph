import { AlertCircle, RefreshCw } from 'lucide-react';

interface ErrorMessageProps {
  /** What failed, e.g. "Unable to load statistics". */
  title: string;
  /** Why it failed, usually `describeError(error)`. */
  message?: string;
  /** Shows a Retry button. */
  onRetry?: () => void;
  retryLabel?: string;
  className?: string;
}

/**
 * Inline error with an optional Retry action, used by every view that loads data.
 */
export default function ErrorMessage({
  title,
  message,
  onRetry,
  retryLabel = 'Retry',
  className = '',
}: ErrorMessageProps) {
  return (
    <div
      role="alert"
      className={`flex flex-col gap-3 rounded-lg border border-red-200 bg-red-50 p-4 sm:flex-row sm:items-center sm:justify-between ${className}`}
    >
      <div className="flex items-start gap-3">
        <AlertCircle className="mt-0.5 h-5 w-5 flex-shrink-0 text-red-500" aria-hidden="true" />
        <div>
          <p className="text-sm font-semibold text-red-800">{title}</p>
          {message && <p className="mt-1 text-sm text-red-700">{message}</p>}
        </div>
      </div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex flex-shrink-0 items-center justify-center gap-2 self-start rounded-md border border-red-300 bg-white px-3 py-1.5 text-sm font-medium text-red-700 transition-colors hover:bg-red-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500 sm:self-auto"
        >
          <RefreshCw className="h-4 w-4" aria-hidden="true" />
          {retryLabel}
        </button>
      )}
    </div>
  );
}
