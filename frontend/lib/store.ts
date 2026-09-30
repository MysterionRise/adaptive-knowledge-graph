/**
 * Global application state using Zustand.
 *
 * Used for cross-page communication and shared state: the current subject (remembered in
 * localStorage), graph highlights sent from the chat, and the learner's mastery, which is
 * synced with the backend.
 */

import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';
import { apiClient } from './api-client';
import { describeError } from './api-errors';
import { INITIAL_MASTERY, type ConceptMastery } from './mastery';
import type { MasteryUpdateResponse, SubjectTheme } from './types';

export const DEFAULT_SUBJECT = 'us_history';

/** localStorage key of the persisted preferences (the current subject). */
export const PREFERENCES_STORAGE_KEY = 'akg-preferences';

// Same format as the backend's subject IDs; anything else in storage is ignored.
const SUBJECT_ID_PATTERN = /^[a-z][a-z0-9_]{0,31}$/;

interface AppState {
  // Subject state (persisted)
  currentSubject: string;
  setCurrentSubject: (subjectId: string) => void;
  subjectTheme: SubjectTheme | null;
  loadSubjectTheme: (subjectId: string) => Promise<void>;

  // Highlighted concepts (from chat to graph)
  highlightedConcepts: string[];
  setHighlightedConcepts: (concepts: string[]) => void;
  clearHighlightedConcepts: () => void;

  // Last query text (for context)
  lastQuery: string | null;
  setLastQuery: (query: string | null) => void;

  // Mastery tracking (synced with backend)
  masteryMap: Record<string, ConceptMastery>;
  updateMastery: (conceptName: string, correct: boolean) => void;

  // Backend sync functions
  syncMasteryToBackend: (concept: string, correct: boolean) => Promise<MasteryUpdateResponse | null>;
  loadMasteryFromBackend: () => Promise<void>;
  /** Reset the learner profile. Rejects with the API error when the backend reset fails. */
  resetMasteryOnBackend: () => Promise<void>;

  // Backend sync state
  isSyncing: boolean;
  /** Message of the last failed profile load or mastery sync (null after a success). */
  lastSyncError: string | null;
}

type PersistedState = Pick<AppState, 'currentSubject'>;

export const useAppStore = create<AppState>()(
  persist(
    (set, get) => ({
      // Subject state
      currentSubject: DEFAULT_SUBJECT,
      setCurrentSubject: (subjectId) => {
        if (subjectId === get().currentSubject) return;
        // Highlights and the last query belong to the previous subject's graph.
        set({ currentSubject: subjectId, highlightedConcepts: [], lastQuery: null });
      },
      subjectTheme: null,
      loadSubjectTheme: async (subjectId) => {
        try {
          const theme = await apiClient.getSubjectTheme(subjectId);
          // Ignore a late response for a subject that is no longer selected.
          if (get().currentSubject === subjectId) set({ subjectTheme: theme });
        } catch (error) {
          // The default colours are used; nothing to show to the user.
          console.warn(`Could not load the theme of subject "${subjectId}": ${describeError(error)}`);
        }
      },

      // Highlighted concepts
      highlightedConcepts: [],
      setHighlightedConcepts: (concepts) => set({ highlightedConcepts: concepts }),
      clearHighlightedConcepts: () => set({ highlightedConcepts: [] }),

      // Last query
      lastQuery: null,
      setLastQuery: (query) => set({ lastQuery: query }),

      // Mastery tracking
      masteryMap: {},

      updateMastery: (conceptName, correct) => {
        const current = get().masteryMap[conceptName] || {
          conceptName,
          masteryLevel: INITIAL_MASTERY,
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

        // Also sync to backend (fire and forget; failures end up in lastSyncError)
        void get().syncMasteryToBackend(conceptName, correct);
      },

      // Backend sync functions
      syncMasteryToBackend: async (concept, correct) => {
        set({ isSyncing: true, lastSyncError: null });

        try {
          const data = await apiClient.updateStudentMastery(concept, correct);

          // Update local state with backend response
          const current = get().masteryMap[concept] || {
            conceptName: concept,
            masteryLevel: INITIAL_MASTERY,
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
          set({ isSyncing: false, lastSyncError: describeError(error) });
          return null;
        }
      },

      loadMasteryFromBackend: async () => {
        set({ isSyncing: true, lastSyncError: null });

        try {
          const data = await apiClient.getStudentProfile();

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
          set({ isSyncing: false, lastSyncError: describeError(error) });
        }
      },

      resetMasteryOnBackend: async () => {
        set({ isSyncing: true });

        try {
          await apiClient.resetStudentProfile();
          // Clear local state only once the backend profile is reset
          set({ masteryMap: {}, isSyncing: false, lastSyncError: null });
        } catch (error) {
          set({ isSyncing: false });
          throw error;
        }
      },

      // Backend sync state
      isSyncing: false,
      lastSyncError: null,
    }),
    {
      name: PREFERENCES_STORAGE_KEY,
      // `window` is undefined during server rendering, which disables persistence there.
      storage: createJSONStorage(() => window.localStorage),
      partialize: (state): PersistedState => ({ currentSubject: state.currentSubject }),
      merge: (persisted, current) => {
        const subject = (persisted as Partial<PersistedState> | undefined)?.currentSubject;
        return typeof subject === 'string' && SUBJECT_ID_PATTERN.test(subject)
          ? { ...current, currentSubject: subject }
          : current;
      },
    }
  )
);
