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

/** Mastery from which a concept counts as mastered. */
export const MASTERY_MASTERED = 0.7;
/** Mastery from which a concept counts as in progress; below it, the concept is still to learn. */
export const MASTERY_IN_PROGRESS = 0.4;

export type MasteryBand = 'mastered' | 'in_progress' | 'to_learn';

/** The band a mastery level falls in: the one classification behind every mastery display. */
export function masteryBand(mastery: number): MasteryBand {
  if (mastery >= MASTERY_MASTERED) return 'mastered';
  if (mastery >= MASTERY_IN_PROGRESS) return 'in_progress';
  return 'to_learn';
}

export const MASTERY_BAND_LABELS: Record<MasteryBand, string> = {
  mastered: 'Mastered',
  in_progress: 'In Progress',
  to_learn: 'To Learn',
};

/**
 * Tailwind classes of each band: a progress bar, a percentage, a card ("chip") and an SVG
 * progress ring. Full literals, so Tailwind's content scanner picks them up.
 */
export const MASTERY_BAND_STYLES: Record<
  MasteryBand,
  { bar: string; text: string; chip: string; stroke: string }
> = {
  mastered: {
    bar: 'bg-emerald-500',
    text: 'text-emerald-600',
    chip: 'text-emerald-600 bg-emerald-50 border-emerald-200',
    stroke: 'stroke-emerald-500',
  },
  in_progress: {
    bar: 'bg-blue-500',
    text: 'text-blue-600',
    chip: 'text-blue-600 bg-blue-50 border-blue-200',
    stroke: 'stroke-blue-500',
  },
  to_learn: {
    bar: 'bg-gray-300',
    text: 'text-gray-400',
    chip: 'text-gray-400 bg-gray-50 border-gray-200',
    stroke: 'stroke-gray-300',
  },
};
