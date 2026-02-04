/**
 * Global application state using Zustand.
 *
 * Used for cross-page communication and shared state.
 */

import { create } from 'zustand';

interface ConceptMastery {
  conceptName: string;
  masteryLevel: number; // 0.0 - 1.0
  attempts: number;
  lastAssessed: string | null;
}

interface AppState {
  // Highlighted concepts (from chat to graph)
  highlightedConcepts: string[];
  setHighlightedConcepts: (concepts: string[]) => void;
  clearHighlightedConcepts: () => void;

  // Last query concepts (for cross-page navigation)
  lastQueryConcepts: string[];
  setLastQueryConcepts: (concepts: string[]) => void;

  // Last query text (for context)
  lastQuery: string | null;
  setLastQuery: (query: string | null) => void;

  // Mastery tracking (simplified client-side for demo)
  masteryMap: Record<string, ConceptMastery>;
  updateMastery: (conceptName: string, correct: boolean) => void;
  getMastery: (conceptName: string) => number;

  // UI state
  isGraphLoading: boolean;
  setGraphLoading: (loading: boolean) => void;
}

export const useAppStore = create<AppState>((set, get) => ({
  // Highlighted concepts
  highlightedConcepts: [],
  setHighlightedConcepts: (concepts) => set({ highlightedConcepts: concepts }),
  clearHighlightedConcepts: () => set({ highlightedConcepts: [] }),

  // Last query concepts
  lastQueryConcepts: [],
  setLastQueryConcepts: (concepts) => set({ lastQueryConcepts: concepts }),

  // Last query
  lastQuery: null,
  setLastQuery: (query) => set({ lastQuery: query }),

  // Mastery tracking
  masteryMap: {},
  updateMastery: (conceptName, correct) => {
    const current = get().masteryMap[conceptName] || {
      conceptName,
      masteryLevel: 0.3, // Initial mastery
      attempts: 0,
      lastAssessed: null,
    };

    // Simple Bayesian-like update
    const delta = correct ? 0.15 : -0.1;
    const newLevel = Math.max(0, Math.min(1, current.masteryLevel + delta));

    set({
      masteryMap: {
        ...get().masteryMap,
        [conceptName]: {
          ...current,
          masteryLevel: newLevel,
          attempts: current.attempts + 1,
          lastAssessed: new Date().toISOString(),
        },
      },
    });
  },
  getMastery: (conceptName) => {
    return get().masteryMap[conceptName]?.masteryLevel ?? 0.3;
  },

  // UI state
  isGraphLoading: false,
  setGraphLoading: (loading) => set({ isGraphLoading: loading }),
}));
