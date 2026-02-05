/**
 * Global application state using Zustand.
 *
 * Used for cross-page communication and shared state.
 * Includes backend sync for student mastery tracking.
 * Includes multi-subject support.
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { SubjectTheme } from './types';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const API_PREFIX = '/api/v1';

interface ConceptMastery {
  conceptName: string;
  masteryLevel: number; // 0.0 - 1.0
  attempts: number;
  lastAssessed: string | null;
}

interface MasteryUpdateResponse {
  concept: string;
  previous_mastery: number;
  new_mastery: number;
  target_difficulty: 'easy' | 'medium' | 'hard';
  total_attempts: number;
}

interface StudentProfileResponse {
  student_id: string;
  overall_ability: number;
  mastery_levels: Record<string, number>;
  updated_at: string;
}

interface AppState {
  // Subject state (persisted)
  currentSubject: string;
  setCurrentSubject: (subjectId: string) => void;
  subjectTheme: SubjectTheme | null;
  loadSubjectTheme: (subjectId: string) => Promise<void>;
  isLoadingTheme: boolean;

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

  // Mastery tracking (synced with backend)
  masteryMap: Record<string, ConceptMastery>;
  updateMastery: (conceptName: string, correct: boolean) => void;
  getMastery: (conceptName: string) => number;

  // Backend sync functions
  syncMasteryToBackend: (concept: string, correct: boolean) => Promise<MasteryUpdateResponse | null>;
  loadMasteryFromBackend: () => Promise<void>;
  resetMasteryOnBackend: () => Promise<void>;

  // Backend sync state
  isSyncing: boolean;
  lastSyncError: string | null;

  // UI state
  isGraphLoading: boolean;
  setGraphLoading: (loading: boolean) => void;
}

export const useAppStore = create<AppState>((set, get) => ({
  // Subject state
  currentSubject: 'us_history', // Default subject
  setCurrentSubject: (subjectId) => {
    set({ currentSubject: subjectId });
    // Save to localStorage for persistence
    if (typeof window !== 'undefined') {
      localStorage.setItem('akg_current_subject', subjectId);
    }
  },
  subjectTheme: null,
  isLoadingTheme: false,
  loadSubjectTheme: async (subjectId: string) => {
    set({ isLoadingTheme: true });
    try {
      const response = await fetch(`${API_BASE}${API_PREFIX}/subjects/${subjectId}/theme`);
      if (response.ok) {
        const theme: SubjectTheme = await response.json();
        set({ subjectTheme: theme, isLoadingTheme: false });
      } else {
        console.error('Failed to load subject theme:', response.status);
        set({ isLoadingTheme: false });
      }
    } catch (error) {
      console.error('Failed to load subject theme:', error);
      set({ isLoadingTheme: false });
    }
  },

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

    // Simple Bayesian-like update (local optimistic update)
    const delta = correct ? 0.15 : -0.1;
    const newLevel = Math.max(0.1, Math.min(1, current.masteryLevel + delta));

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

    // Also sync to backend (fire and forget)
    get().syncMasteryToBackend(conceptName, correct);
  },

  getMastery: (conceptName) => {
    return get().masteryMap[conceptName]?.masteryLevel ?? 0.3;
  },

  // Backend sync functions
  syncMasteryToBackend: async (concept: string, correct: boolean): Promise<MasteryUpdateResponse | null> => {
    set({ isSyncing: true, lastSyncError: null });

    try {
      const response = await fetch(`${API_BASE}${API_PREFIX}/student/mastery`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ concept, correct }),
      });

      if (!response.ok) {
        throw new Error(`Failed to sync mastery: ${response.status}`);
      }

      const data: MasteryUpdateResponse = await response.json();

      // Update local state with backend response
      const current = get().masteryMap[concept] || {
        conceptName: concept,
        masteryLevel: 0.3,
        attempts: 0,
        lastAssessed: null,
      };

      set({
        masteryMap: {
          ...get().masteryMap,
          [concept]: {
            ...current,
            masteryLevel: data.new_mastery,
            attempts: data.total_attempts,
            lastAssessed: new Date().toISOString(),
          },
        },
        isSyncing: false,
      });

      return data;
    } catch (error) {
      console.error('Failed to sync mastery to backend:', error);
      set({
        isSyncing: false,
        lastSyncError: error instanceof Error ? error.message : 'Unknown error'
      });
      return null;
    }
  },

  loadMasteryFromBackend: async (): Promise<void> => {
    set({ isSyncing: true, lastSyncError: null });

    try {
      const response = await fetch(`${API_BASE}${API_PREFIX}/student/profile`);

      if (!response.ok) {
        throw new Error(`Failed to load profile: ${response.status}`);
      }

      const data: StudentProfileResponse = await response.json();

      // Convert backend format to local format
      const masteryMap: Record<string, ConceptMastery> = {};
      for (const [concept, level] of Object.entries(data.mastery_levels)) {
        masteryMap[concept] = {
          conceptName: concept,
          masteryLevel: level,
          attempts: 0, // Backend doesn't return this in profile summary
          lastAssessed: data.updated_at,
        };
      }

      set({ masteryMap, isSyncing: false });
    } catch (error) {
      console.error('Failed to load mastery from backend:', error);
      set({
        isSyncing: false,
        lastSyncError: error instanceof Error ? error.message : 'Unknown error'
      });
    }
  },

  resetMasteryOnBackend: async (): Promise<void> => {
    set({ isSyncing: true, lastSyncError: null });

    try {
      const response = await fetch(`${API_BASE}${API_PREFIX}/student/reset`, {
        method: 'POST',
      });

      if (!response.ok) {
        throw new Error(`Failed to reset profile: ${response.status}`);
      }

      // Clear local state
      set({ masteryMap: {}, isSyncing: false });
    } catch (error) {
      console.error('Failed to reset mastery on backend:', error);
      set({
        isSyncing: false,
        lastSyncError: error instanceof Error ? error.message : 'Unknown error'
      });
    }
  },

  // Backend sync state
  isSyncing: false,
  lastSyncError: null,

  // UI state
  isGraphLoading: false,
  setGraphLoading: (loading) => set({ isGraphLoading: loading }),
}));
