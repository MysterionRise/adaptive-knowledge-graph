import type { Metadata } from 'next';
import type { ReactNode } from 'react';

// The page is a client component, so its metadata lives in this server layout.
export const metadata: Metadata = {
  title: 'Demo Status',
  description: 'Readiness of the local services, subject data and latest evaluation.',
};

export default function DemoStatusLayout({ children }: { children: ReactNode }) {
  return children;
}
