import type { Metadata } from 'next';
import type { ReactNode } from 'react';

// The page is a client component, so its metadata lives in this server layout.
export const metadata: Metadata = {
  title: 'Knowledge Graph',
  description: 'Explore the concepts of a subject and their prerequisite relationships.',
};

export default function GraphLayout({ children }: { children: ReactNode }) {
  return children;
}
