import type { ReactNode } from 'react';

interface PageHeaderProps {
  title: string;
  /** Controls shown at the right end of the band (a toggle, a refresh button, ...). */
  actions?: ReactNode;
  /** Width of the band's content, matching the page's `main` (default `max-w-7xl`). */
  maxWidthClassName?: string;
  className?: string;
}

/**
 * The white band with the page's `h1` under the navigation bar: every page has exactly one,
 * sized and padded like its content.
 */
export default function PageHeader({
  title,
  actions,
  maxWidthClassName,
  className,
}: PageHeaderProps) {
  return (
    <header className={`border-b border-gray-200 bg-white ${className ?? ''}`}>
      <div
        className={`mx-auto flex ${maxWidthClassName ?? 'max-w-7xl'} flex-wrap items-center justify-between gap-3 px-4 py-4 sm:px-6 lg:px-8`}
      >
        <h1 className="text-xl font-semibold tracking-tight text-gray-900">{title}</h1>
        {actions}
      </div>
    </header>
  );
}
