import { masteryLevelOf } from '@/lib/mastery';
import { PREFERENCES_STORAGE_KEY, useAppStore } from '@/lib/store';
import { json, mockApi } from './helpers/mockApi';

// The store talks to the backend through the real API client, answered by the routed mock.
jest.mock('@/lib/api-client', () => {
  const actual = jest.requireActual('@/lib/api-client');
  return {
    ...actual,
    __esModule: true,
    apiClient: new actual.default('http://localhost:8000', {
      adapter: (config: unknown) => require('./helpers/mockApi').mockApi.adapter(config),
    }),
  };
});

const MASTERY = 'POST /api/v1/student/mastery';
const PROFILE = 'GET /api/v1/student/profile';
const RESET = 'POST /api/v1/student/reset';

const masteryReply = (concept: string, newMastery: number, totalAttempts = 1) =>
  json({
    concept,
    previous_mastery: 0.3,
    new_mastery: newMastery,
    target_difficulty: 'medium',
    total_attempts: totalAttempts,
  });

const mastery = (concept: string) => masteryLevelOf(useAppStore.getState().masteryMap, concept);

/** Resolves once no backend sync is in flight (updateMastery syncs fire-and-forget). */
const syncSettled = () =>
  new Promise<void>((resolve) => {
    if (!useAppStore.getState().isSyncing) {
      resolve();
      return;
    }
    const unsubscribe = useAppStore.subscribe((state) => {
      if (!state.isSyncing) {
        unsubscribe();
        resolve();
      }
    });
  });

describe('useAppStore', () => {
  beforeEach(() => {
    // Reset store to initial state
    useAppStore.setState({
      currentSubject: 'us_history',
      subjectTheme: null,
      highlightedConcepts: [],
      lastQuery: null,
      masteryMap: {},
      isSyncing: false,
      lastSyncError: null,
    });
    mockApi.reset();
  });

  afterEach(async () => {
    // Never let a pending sync from one test update the store during the next one
    await syncSettled();
    jest.restoreAllMocks();
    expect(mockApi.unexpected).toEqual([]);
  });

  describe('Highlighted Concepts', () => {
    it('sets highlighted concepts', () => {
      useAppStore.getState().setHighlightedConcepts(['Concept A', 'Concept B']);

      expect(useAppStore.getState().highlightedConcepts).toEqual(['Concept A', 'Concept B']);
    });

    it('clears highlighted concepts', () => {
      const { setHighlightedConcepts, clearHighlightedConcepts } = useAppStore.getState();

      setHighlightedConcepts(['Concept A']);
      clearHighlightedConcepts();

      expect(useAppStore.getState().highlightedConcepts).toEqual([]);
    });

    it('replaces previous concepts when setting new ones', () => {
      const { setHighlightedConcepts } = useAppStore.getState();

      setHighlightedConcepts(['Old Concept']);
      setHighlightedConcepts(['New Concept']);

      expect(useAppStore.getState().highlightedConcepts).toEqual(['New Concept']);
    });
  });

  describe('Last Query', () => {
    it('sets and clears the last query', () => {
      const { setLastQuery } = useAppStore.getState();

      setLastQuery('What is the American Revolution?');
      expect(useAppStore.getState().lastQuery).toBe('What is the American Revolution?');

      setLastQuery(null);
      expect(useAppStore.getState().lastQuery).toBeNull();
    });
  });

  describe('Subject', () => {
    it('sets the current subject and remembers it in localStorage', () => {
      useAppStore.getState().setCurrentSubject('economics');

      expect(useAppStore.getState().currentSubject).toBe('economics');
      expect(JSON.parse(localStorage.getItem(PREFERENCES_STORAGE_KEY) ?? '{}')).toEqual({
        state: { currentSubject: 'economics' },
        version: 0,
      });
    });

    it('only persists the subject', () => {
      useAppStore.getState().setHighlightedConcepts(['Concept A']);

      const stored = JSON.parse(localStorage.getItem(PREFERENCES_STORAGE_KEY) ?? '{}');
      expect(Object.keys(stored.state)).toEqual(['currentSubject']);
    });

    it('clears graph highlights from the previous subject', () => {
      useAppStore.setState({ highlightedConcepts: ['Stamp Act'], lastQuery: 'Why?' });

      useAppStore.getState().setCurrentSubject('economics');

      expect(useAppStore.getState()).toMatchObject({ highlightedConcepts: [], lastQuery: null });
    });

    it('keeps highlights when the subject does not change', () => {
      useAppStore.setState({ highlightedConcepts: ['Stamp Act'] });

      useAppStore.getState().setCurrentSubject('us_history');

      expect(useAppStore.getState().highlightedConcepts).toEqual(['Stamp Act']);
    });

    it('loads the theme of the current subject', async () => {
      const theme = {
        subject_id: 'economics',
        primary_color: '#d97706',
        secondary_color: '#fbbf24',
        accent_color: '#f59e0b',
        chapter_colors: {},
      };
      mockApi.on('GET /api/v1/subjects/economics/theme', json(theme));
      useAppStore.getState().setCurrentSubject('economics');

      await useAppStore.getState().loadSubjectTheme('economics');

      expect(useAppStore.getState().subjectTheme).toEqual(theme);
    });

    it('ignores a theme that arrives after the subject changed', async () => {
      mockApi.on('GET /api/v1/subjects/economics/theme', json({ subject_id: 'economics' }));

      const loading = useAppStore.getState().loadSubjectTheme('economics');
      await loading;

      // The current subject is still us_history
      expect(useAppStore.getState().subjectTheme).toBeNull();
    });

    it('keeps the previous theme when the theme request fails', async () => {
      const warn = jest.spyOn(console, 'warn').mockImplementation(() => {});
      mockApi.on('GET /api/v1/subjects/unknown/theme', json({ detail: 'Subject not found' }, 404));
      useAppStore.setState({ currentSubject: 'unknown' });

      await useAppStore.getState().loadSubjectTheme('unknown');

      expect(useAppStore.getState().subjectTheme).toBeNull();
      expect(warn).toHaveBeenCalledTimes(1);
      expect(warn).toHaveBeenCalledWith(
        'Could not load the theme of subject "unknown": Subject not found'
      );
    });
  });

  describe('Subject persistence', () => {
    afterEach(() => {
      localStorage.clear();
    });

    /** Load a fresh copy of the store module, as after a page reload. */
    function reloadStore() {
      let store!: typeof useAppStore;
      jest.isolateModules(() => {
        store = require('@/lib/store').useAppStore;
      });
      return store;
    }

    it('restores the remembered subject after a reload', () => {
      localStorage.setItem(
        PREFERENCES_STORAGE_KEY,
        JSON.stringify({ state: { currentSubject: 'economics' }, version: 0 })
      );

      const store = reloadStore();

      expect(store.getState().currentSubject).toBe('economics');
      // The server-rendered markup uses the default subject; React hydrates with it first.
      expect(store.getInitialState().currentSubject).toBe('us_history');
    });

    it.each([
      ['an invalid subject ID', JSON.stringify({ state: { currentSubject: '<script>' }, version: 0 })],
      ['a non-string subject', JSON.stringify({ state: { currentSubject: 42 }, version: 0 })],
      ['corrupt JSON', '{not json'],
    ])('falls back to the default subject for %s', (_label, stored) => {
      localStorage.setItem(PREFERENCES_STORAGE_KEY, stored);

      expect(reloadStore().getState().currentSubject).toBe('us_history');
    });
  });

  describe('Mastery Tracking', () => {
    it('initializes mastery for new concept', () => {
      expect(mastery('New Concept')).toBe(0.3); // Default initial mastery
    });

    it('updates mastery on correct answer', async () => {
      mockApi.on(MASTERY, masteryReply('Test Concept', 0.45));

      useAppStore.getState().updateMastery('Test Concept', true);

      // Local optimistic update
      expect(mastery('Test Concept')).toBeCloseTo(0.45, 1); // 0.3 + 0.15 = 0.45
      await syncSettled();
    });

    it('updates mastery on incorrect answer', async () => {
      mockApi.on(MASTERY, masteryReply('Test Concept', 0.2));

      useAppStore.getState().updateMastery('Test Concept', false);

      expect(mastery('Test Concept')).toBeCloseTo(0.2, 1); // 0.3 - 0.1 = 0.2
      await syncSettled();
    });

    it('clamps mastery to minimum 0.1', async () => {
      mockApi.on(MASTERY, masteryReply('Low Concept', 0.1));
      useAppStore.setState({
        masteryMap: {
          'Low Concept': { conceptName: 'Low Concept', masteryLevel: 0.15, attempts: 0, lastAssessed: null },
        },
      });

      useAppStore.getState().updateMastery('Low Concept', false);

      expect(mastery('Low Concept')).toBe(0.1);
      await syncSettled();
    });

    it('clamps mastery to maximum 1.0', async () => {
      mockApi.on(MASTERY, masteryReply('High Concept', 1.0));
      useAppStore.setState({
        masteryMap: {
          'High Concept': { conceptName: 'High Concept', masteryLevel: 0.95, attempts: 0, lastAssessed: null },
        },
      });

      useAppStore.getState().updateMastery('High Concept', true);

      expect(mastery('High Concept')).toBe(1.0);
      await syncSettled();
    });

    it('increments attempts and sets the assessment time', async () => {
      mockApi.on(MASTERY, masteryReply('Attempt Concept', 0.45));

      useAppStore.getState().updateMastery('Attempt Concept', true);

      const entry = useAppStore.getState().masteryMap['Attempt Concept'];
      expect(entry.attempts).toBe(1);
      expect(entry.lastAssessed).not.toBeNull();
      await syncSettled();
    });
  });

  describe('Backend Sync', () => {
    it('syncs mastery to backend on update', async () => {
      mockApi.on(MASTERY, masteryReply('Sync Concept', 0.52, 3));

      useAppStore.getState().updateMastery('Sync Concept', true);
      await syncSettled();

      expect(mockApi.calls(MASTERY)[0].body).toEqual({ concept: 'Sync Concept', correct: true });
      // The backend's estimate replaces the optimistic local value
      const entry = useAppStore.getState().masteryMap['Sync Concept'];
      expect(entry.masteryLevel).toBe(0.52);
      expect(entry.attempts).toBe(3);
    });

    it('records the detail of a failed sync', async () => {
      mockApi.on(MASTERY, json({ detail: 'Rate limit exceeded: 30 per 1 minute' }, 429));

      const result = await useAppStore.getState().syncMasteryToBackend('Error Concept', true);

      expect(result).toBeNull();
      expect(useAppStore.getState()).toMatchObject({
        isSyncing: false,
        lastSyncError: 'Rate limit exceeded: 30 per 1 minute',
      });
    });

    it('sets isSyncing during sync', async () => {
      let reply!: () => void;
      mockApi.on(
        MASTERY,
        () =>
          new Promise((resolve) => {
            reply = () => resolve(masteryReply('Sync Concept', 0.45));
          })
      );

      const syncPromise = useAppStore.getState().syncMasteryToBackend('Sync Concept', true);

      expect(useAppStore.getState().isSyncing).toBe(true);
      await new Promise((resolve) => setTimeout(resolve, 0));
      reply();
      await expect(syncPromise).resolves.toEqual(expect.objectContaining({ new_mastery: 0.45 }));
      expect(useAppStore.getState().isSyncing).toBe(false);
    });
  });

  describe('Load Mastery from Backend', () => {
    it('loads mastery profile from backend', async () => {
      mockApi.on(
        PROFILE,
        json({
          student_id: 'test-student',
          overall_ability: 0.6,
          mastery_levels: { 'Concept A': 0.8, 'Concept B': 0.5 },
          updated_at: '2024-01-01T00:00:00Z',
        })
      );

      await useAppStore.getState().loadMasteryFromBackend();

      expect(mastery('Concept A')).toBe(0.8);
      expect(mastery('Concept B')).toBe(0.5);
      expect(useAppStore.getState()).toMatchObject({ isSyncing: false, lastSyncError: null });
    });

    it('records the detail of a failed load', async () => {
      mockApi.on(PROFILE, json({ detail: 'Missing or invalid API key' }, 401));

      await useAppStore.getState().loadMasteryFromBackend();

      expect(useAppStore.getState().lastSyncError).toBe('Missing or invalid API key');
    });
  });

  describe('Reset Mastery', () => {
    const someMastery = {
      'Concept A': { conceptName: 'Concept A', masteryLevel: 0.8, attempts: 5, lastAssessed: '2024-01-01' },
    };

    it('resets mastery on backend', async () => {
      mockApi.on(RESET, json({ student_id: 'default', mastery_levels: {} }));
      useAppStore.setState({ masteryMap: someMastery, lastSyncError: 'old failure' });

      await useAppStore.getState().resetMasteryOnBackend();

      expect(mastery('Concept A')).toBe(0.3);
      expect(mockApi.calls(RESET)).toHaveLength(1);
      expect(useAppStore.getState()).toMatchObject({ isSyncing: false, lastSyncError: null });
    });

    it('rejects and keeps local mastery when the reset fails', async () => {
      mockApi.on(RESET, json({ detail: 'An internal error occurred' }, 500));
      useAppStore.setState({ masteryMap: someMastery });

      await expect(useAppStore.getState().resetMasteryOnBackend()).rejects.toMatchObject({
        status: 500,
        message: 'An internal error occurred',
      });

      expect(mastery('Concept A')).toBe(0.8);
      expect(useAppStore.getState().isSyncing).toBe(false);
    });
  });

  describe('State Isolation', () => {
    it('maintains separate state for different properties', async () => {
      mockApi.on(MASTERY, masteryReply('Test', 0.45));
      const { setHighlightedConcepts, setLastQuery, updateMastery } = useAppStore.getState();

      setHighlightedConcepts(['Concept']);
      setLastQuery('Query');
      updateMastery('Test', true);

      const state = useAppStore.getState();
      expect(state.highlightedConcepts).toEqual(['Concept']);
      expect(state.lastQuery).toBe('Query');
      expect(state.masteryMap['Test']).toBeDefined();
      await syncSettled();
    });
  });
});

describe('masteryLevelOf', () => {
  it('returns the stored mastery or the initial mastery', () => {
    const map = { A: { conceptName: 'A', masteryLevel: 0.9, attempts: 1, lastAssessed: null } };

    expect(masteryLevelOf(map, 'A')).toBe(0.9);
    expect(masteryLevelOf(map, 'B')).toBe(0.3);
  });
});
