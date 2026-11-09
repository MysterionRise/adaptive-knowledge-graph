'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Network } from 'lucide-react';
import SubjectPicker from './SubjectPicker';

const NAV_LINKS = [
  { href: '/graph', label: 'Graph' },
  { href: '/chat', label: 'AI Tutor' },
  { href: '/comparison', label: 'Compare' },
  { href: '/assessment', label: 'Assessment' },
  { href: '/demo-status', label: 'Demo Status' },
  { href: '/about', label: 'About' },
] as const;

const isActive = (pathname: string, href: string) =>
  pathname === href || pathname.startsWith(`${href}/`);

/**
 * Site-wide navigation with the subject picker, rendered by the root layout on every page.
 */
export default function NavBar() {
  const pathname = usePathname() ?? '';

  return (
    <nav aria-label="Main" className="bg-gray-900 text-gray-100">
      <div className="mx-auto flex h-nav max-w-7xl items-center gap-4 px-4 sm:px-6 lg:px-8">
        <Link
          href="/"
          aria-current={pathname === '/' ? 'page' : undefined}
          className="flex flex-shrink-0 items-center gap-2 py-3 text-sm font-semibold text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-400"
        >
          <Network className="h-5 w-5 text-primary-400" aria-hidden="true" />
          Adaptive Knowledge Graph
        </Link>
        {/* The list scrolls on narrow screens; the container must not clip the picker's listbox */}
        <ul className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
          {NAV_LINKS.map(({ href, label }) => {
            const active = isActive(pathname, href);
            return (
              <li key={href}>
                <Link
                  href={href}
                  aria-current={active ? 'page' : undefined}
                  className={`block whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-400 ${
                    active ? 'bg-gray-700 text-white' : 'text-gray-300 hover:bg-gray-800 hover:text-white'
                  }`}
                >
                  {label}
                </Link>
              </li>
            );
          })}
        </ul>
        <SubjectPicker className="ml-auto shrink-0" />
      </div>
    </nav>
  );
}
