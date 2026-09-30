import type { Metadata } from 'next';
import type { ReactNode } from 'react';

// The page is a client component, so its metadata lives in this server layout.
export const metadata: Metadata = {
  title: 'Adaptive Assessment',
  description: 'Quizzes generated from the textbook, adapted to your mastery of each topic.',
};

export default function AssessmentLayout({ children }: { children: ReactNode }) {
  return children;
}
