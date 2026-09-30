import type { Difficulty } from './types';

/** Mastery assumed for a concept the learner has not practised yet (same as the backend). */
export const INITIAL_MASTERY = 0.3;

export interface ConceptMastery {
  conceptName: string;
  masteryLevel: number; // 0.0 - 1.0
  attempts: number;
  lastAssessed: string | null;
}

/** Mastery of a concept, or the initial mastery when it has not been assessed yet. */
export function masteryLevelOf(masteryMap: Record<string, ConceptMastery>, concept: string): number {
  return masteryMap[concept]?.masteryLevel ?? INITIAL_MASTERY;
}

/** Question difficulty the backend targets for a mastery level. */
export function targetDifficultyFor(mastery: number): Difficulty {
  if (mastery < 0.4) return 'easy';
  if (mastery <= 0.7) return 'medium';
  return 'hard';
}
