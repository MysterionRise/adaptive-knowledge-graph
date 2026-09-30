import type { SubjectSummary } from './types';

/** Subjects without knowledge-graph data are listed but cannot be selected. */
export function isSubjectAvailable(subject: SubjectSummary): boolean {
  // Older backends do not send `available`; treat those subjects as available.
  return subject.available !== false;
}
