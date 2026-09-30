import type { Metadata } from 'next';
import type { ReactNode } from 'react';

// The page is a client component, so its metadata lives in this server layout.
export const metadata: Metadata = {
  title: 'KG-RAG vs Regular RAG',
  description: 'Compare answers with and without knowledge-graph query expansion.',
};

export default function ComparisonLayout({ children }: { children: ReactNode }) {
  return children;
}
