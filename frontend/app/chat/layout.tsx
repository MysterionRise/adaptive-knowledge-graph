import type { Metadata } from 'next';
import type { ReactNode } from 'react';

// The page is a client component, so its metadata lives in this server layout.
export const metadata: Metadata = {
  title: 'AI Tutor',
  description: 'Ask questions and get answers grounded in the textbook, with sources.',
};

export default function ChatLayout({ children }: { children: ReactNode }) {
  return children;
}
