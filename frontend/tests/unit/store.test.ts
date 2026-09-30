import { useAppStore } from '@/lib/store';

// Mock fetch. Each test queues the responses it expects; anything else is rejected.
const fetchMock = jest.fn();
const originalFetch = global.fetch;

const jsonResponse = (body: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
});

const masteryResponse = (concept: string, newMastery: number, totalAttempts = 1) =>
  jsonResponse({
    concept,
    previous_mastery: 0.3,
    new_mastery: newMastery,
    target_difficulty: 'medium',
    total_attempts: totalAttempts,
  });

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

beforeAll(() => {
  global.fetch = fetchMock as unknown as typeof fetch;
});

afterAll(() => {
  global.fetch = originalFetch;
});

describe('useAppStore', () => {
  beforeEach(() => {
    // Reset store to initial state
    useAppStore.setState({
      currentSubject: 'us_history',
      subjectTheme: null,
      isLoadingTheme: false,
      highlightedConcepts: [],
      lastQueryConcepts: [],
      lastQuery: null,
      masteryMap: {},
      isSyncing: false,
      lastSyncError: null,
      isGraphLoading: false,
    });
    jest.clearAllMocks();
    // mockReset also drops implementations left behind by a previous test
    fetchMock.mockReset();
    fetchMock.mockImplementation((url: string) =>
      Promise.reject(new Error(`Unexpected fetch: ${url}`))
    );
  });

  afterEach(async () => {
    // Never let a pending sync from one test update the store during the next one
    await syncSettled();
    jest.restoreAllMocks();
  });

  describe('Highlighted Concepts', () => {
    it('sets highlighted concepts', () => {
      const { setHighlightedConcepts } = useAppStore.getState();

      setHighlightedConcepts(['Concept A', 'Concept B']);

      const { highlightedConcepts } = useAppStore.getState();
      expect(highlightedConcepts).toEqual(['Concept A', 'Concept B']);
    });

    it('clears highlighted concepts', () => {
      const { setHighlightedConcepts, clearHighlightedConcepts } = useAppStore.getState();

      setHighlightedConcepts(['Concept A']);
      clearHighlightedConcepts();

      const { highlightedConcepts } = useAppStore.getState();
      expect(highlightedConcepts).toEqual([]);
    });

    it('replaces previous concepts when setting new ones', () => {
      const { setHighlightedConcepts } = useAppStore.getState();

      setHighlightedConcepts(['Old Concept']);
      setHighlightedConcepts(['New Concept']);

      const { highlightedConcepts } = useAppStore.getState();
      expect(highlightedConcepts).toEqual(['New Concept']);
    });
  });

  describe('Last Query Concepts', () => {
    it('sets last query concepts', () => {
      const { setLastQueryConcepts } = useAppStore.getState();

      setLastQueryConcepts(['Query Concept 1', 'Query Concept 2']);

      const { lastQueryConcepts } = useAppStore.getState();
      expect(lastQueryConcepts).toEqual(['Query Concept 1', 'Query Concept 2']);
    });
  });

  describe('Last Query', () => {
    it('sets last query', () => {
      const { setLastQuery } = useAppStore.getState();

      setLastQuery('What is the American Revolution?');

      const { lastQuery } = useAppStore.getState();
      expect(lastQuery).toBe('What is the American Revolution?');
    });

    it('clears last query', () => {
      const { setLastQuery } = useAppStore.getState();

      setLastQuery('Some query');
      setLastQuery(null);

      const { lastQuery } = useAppStore.getState();
      expect(lastQuery).toBeNull();
    });
  });

  describe('Subject', () => {
    it('sets the current subject and remembers it', () => {
      const setItem = jest.spyOn(Storage.prototype, 'setItem');

      useAppStore.getState().setCurrentSubject('economics');

      expect(useAppStore.getState().currentSubject).toBe('economics');
      expect(setItem).toHaveBeenCalledWith('akg_current_subject', 'economics');
    });

    it('loads the subject theme', async () => {
      const theme = {
        subject_id: 'economics',
        primary_color: '#d97706',
        secondary_color: '#fbbf24',
        accent_color: '#f59e0b',
        chapter_colors: {},
      };
      fetchMock.mockResolvedValueOnce(jsonResponse(theme));

      await useAppStore.getState().loadSubjectTheme('economics');

      expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/subjects/economics/theme'));
      expect(useAppStore.getState().subjectTheme).toEqual(theme);
      expect(useAppStore.getState().isLoadingTheme).toBe(false);
    });

    it('keeps the previous theme when the theme request fails', async () => {
      const consoleError = jest.spyOn(console, 'error').mockImplementation(() => {});
      fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'Not found' }, 404));

      await useAppStore.getState().loadSubjectTheme('unknown');

      expect(useAppStore.getState().subjectTheme).toBeNull();
      expect(useAppStore.getState().isLoadingTheme).toBe(false);
      expect(consoleError).toHaveBeenCalledWith('Failed to load subject theme:', 404);
    });

    it('handles theme network errors gracefully', async () => {
      const consoleError = jest.spyOn(console, 'error').mockImplementation(() => {});
      fetchMock.mockRejectedValueOnce(new Error('Network error'));

      await useAppStore.getState().loadSubjectTheme('economics');

      expect(useAppStore.getState().isLoadingTheme).toBe(false);
      expect(consoleError).toHaveBeenCalled();
    });
  });

  describe('Mastery Tracking', () => {
    it('initializes mastery for new concept', () => {
      const { getMastery } = useAppStore.getState();

      const mastery = getMastery('New Concept');

      expect(mastery).toBe(0.3); // Default initial mastery
    });

    it('updates mastery on correct answer', async () => {
      fetchMock.mockResolvedValueOnce(masteryResponse('Test Concept', 0.45));

      const { updateMastery, getMastery } = useAppStore.getState();

      updateMastery('Test Concept', true);

      // Local optimistic update
      const mastery = getMastery('Test Concept');
      expect(mastery).toBeCloseTo(0.45, 1); // 0.3 + 0.15 = 0.45
      await syncSettled();
    });

    it('updates mastery on incorrect answer', async () => {
      fetchMock.mockResolvedValueOnce(masteryResponse('Test Concept', 0.2));

      const { updateMastery, getMastery } = useAppStore.getState();

      updateMastery('Test Concept', false);

      const mastery = getMastery('Test Concept');
      expect(mastery).toBeCloseTo(0.2, 1); // 0.3 - 0.1 = 0.2
      await syncSettled();
    });

    it('clamps mastery to minimum 0.1', async () => {
      fetchMock.mockResolvedValueOnce(masteryResponse('Low Concept', 0.1));

      const { updateMastery, getMastery } = useAppStore.getState();

      // Set initial low mastery
      useAppStore.setState({
        masteryMap: {
          'Low Concept': {
            conceptName: 'Low Concept',
            masteryLevel: 0.15,
            attempts: 0,
            lastAssessed: null,
          },
        },
      });

      updateMastery('Low Concept', false);

      expect(getMastery('Low Concept')).toBe(0.1);
      await syncSettled();
    });

    it('clamps mastery to maximum 1.0', async () => {
      fetchMock.mockResolvedValueOnce(masteryResponse('High Concept', 1.0));

      const { updateMastery, getMastery } = useAppStore.getState();

      // Set initial high mastery
      useAppStore.setState({
        masteryMap: {
          'High Concept': {
            conceptName: 'High Concept',
            masteryLevel: 0.95,
            attempts: 0,
            lastAssessed: null,
          },
        },
      });

      updateMastery('High Concept', true);

      expect(getMastery('High Concept')).toBe(1.0);
      await syncSettled();
    });

    it('increments attempts counter', async () => {
      fetchMock.mockResolvedValueOnce(masteryResponse('Attempt Concept', 0.45));

      const { updateMastery } = useAppStore.getState();

      updateMastery('Attempt Concept', true);

      const { masteryMap } = useAppStore.getState();
      expect(masteryMap['Attempt Concept'].attempts).toBe(1);
      await syncSettled();
    });

    it('sets lastAssessed timestamp', async () => {
      fetchMock.mockResolvedValueOnce(masteryResponse('Timestamp Concept', 0.45));

      const { updateMastery } = useAppStore.getState();

      updateMastery('Timestamp Concept', true);

      const { masteryMap } = useAppStore.getState();
      expect(masteryMap['Timestamp Concept'].lastAssessed).not.toBeNull();
      await syncSettled();
    });
  });

  describe('Backend Sync', () => {
    it('syncs mastery to backend on update', async () => {
      fetchMock.mockResolvedValueOnce(masteryResponse('Sync Concept', 0.52, 3));

      const { updateMastery } = useAppStore.getState();

      updateMastery('Sync Concept', true);

      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/student/mastery'),
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ concept: 'Sync Concept', correct: true }),
        })
      );

      await syncSettled();

      // The backend's estimate replaces the optimistic local value
      const entry = useAppStore.getState().masteryMap['Sync Concept'];
      expect(entry.masteryLevel).toBe(0.52);
      expect(entry.attempts).toBe(3);
    });

    it('handles sync errors gracefully', async () => {
      const consoleError = jest.spyOn(console, 'error').mockImplementation(() => {});
      fetchMock.mockRejectedValueOnce(new Error('Network error'));

      const { syncMasteryToBackend } = useAppStore.getState();

      const result = await syncMasteryToBackend('Error Concept', true);

      expect(result).toBeNull();

      const { lastSyncError, isSyncing } = useAppStore.getState();
      expect(lastSyncError).toBe('Network error');
      expect(isSyncing).toBe(false);
      expect(consoleError).toHaveBeenCalled();
    });

    it('reports HTTP errors from the mastery endpoint', async () => {
      jest.spyOn(console, 'error').mockImplementation(() => {});
      fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'boom' }, 500));

      const result = await useAppStore.getState().syncMasteryToBackend('Error Concept', true);

      expect(result).toBeNull();
      expect(useAppStore.getState().lastSyncError).toBe('Failed to sync mastery: 500');
    });

    it('sets isSyncing during sync', async () => {
      let resolveFetch!: (response: unknown) => void;
      fetchMock.mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveFetch = resolve;
          })
      );

      const { syncMasteryToBackend } = useAppStore.getState();

      const syncPromise = syncMasteryToBackend('Sync Concept', true);

      // Check isSyncing is true during sync
      expect(useAppStore.getState().isSyncing).toBe(true);

      resolveFetch(masteryResponse('Sync Concept', 0.45));
      const result = await syncPromise;

      expect(result).toEqual(expect.objectContaining({ new_mastery: 0.45 }));
      expect(useAppStore.getState().isSyncing).toBe(false);
    });
  });

  describe('Load Mastery from Backend', () => {
    it('loads mastery profile from backend', async () => {
      fetchMock.mockResolvedValueOnce(
        jsonResponse({
          student_id: 'test-student',
          overall_ability: 0.6,
          mastery_levels: {
            'Concept A': 0.8,
            'Concept B': 0.5,
          },
          updated_at: '2024-01-01T00:00:00Z',
        })
      );

      const { loadMasteryFromBackend, getMastery } = useAppStore.getState();

      await loadMasteryFromBackend();

      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/student/profile'),
        expect.any(Object)
      );
      expect(getMastery('Concept A')).toBe(0.8);
      expect(getMastery('Concept B')).toBe(0.5);
      expect(useAppStore.getState().isSyncing).toBe(false);
    });

    it('handles load errors gracefully', async () => {
      jest.spyOn(console, 'error').mockImplementation(() => {});
      fetchMock.mockRejectedValueOnce(new Error('Load failed'));

      const { loadMasteryFromBackend } = useAppStore.getState();

      await loadMasteryFromBackend();

      const { lastSyncError } = useAppStore.getState();
      expect(lastSyncError).toBe('Load failed');
    });

    it('reports HTTP errors from the profile endpoint', async () => {
      jest.spyOn(console, 'error').mockImplementation(() => {});
      fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'Unauthorized' }, 401));

      await useAppStore.getState().loadMasteryFromBackend();

      expect(useAppStore.getState().lastSyncError).toBe('Failed to load profile: 401');
    });
  });

  describe('Reset Mastery', () => {
    it('resets mastery on backend', async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse({ message: 'Reset successful' }));

      // Set some initial mastery
      useAppStore.setState({
        masteryMap: {
          'Concept A': {
            conceptName: 'Concept A',
            masteryLevel: 0.8,
            attempts: 5,
            lastAssessed: '2024-01-01',
          },
        },
      });

      const { resetMasteryOnBackend, getMastery } = useAppStore.getState();

      await resetMasteryOnBackend();

      // Local mastery should be cleared
      expect(getMastery('Concept A')).toBe(0.3); // Default value

      // API should have been called
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/student/reset'),
        expect.objectContaining({ method: 'POST' })
      );
    });

    it('handles reset errors gracefully', async () => {
      jest.spyOn(console, 'error').mockImplementation(() => {});
      fetchMock.mockRejectedValueOnce(new Error('Reset failed'));

      const { resetMasteryOnBackend } = useAppStore.getState();

      await resetMasteryOnBackend();

      const { lastSyncError } = useAppStore.getState();
      expect(lastSyncError).toBe('Reset failed');
    });

    it('keeps local mastery when the reset endpoint returns an error', async () => {
      jest.spyOn(console, 'error').mockImplementation(() => {});
      fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'boom' }, 500));
      useAppStore.setState({
        masteryMap: {
          'Concept A': {
            conceptName: 'Concept A',
            masteryLevel: 0.8,
            attempts: 5,
            lastAssessed: '2024-01-01',
          },
        },
      });

      await useAppStore.getState().resetMasteryOnBackend();

      expect(useAppStore.getState().getMastery('Concept A')).toBe(0.8);
      expect(useAppStore.getState().lastSyncError).toBe('Failed to reset profile: 500');
    });
  });

  describe('UI State', () => {
    it('sets graph loading state', () => {
      const { setGraphLoading } = useAppStore.getState();

      setGraphLoading(true);

      const { isGraphLoading } = useAppStore.getState();
      expect(isGraphLoading).toBe(true);

      setGraphLoading(false);

      const { isGraphLoading: isLoadingAfter } = useAppStore.getState();
      expect(isLoadingAfter).toBe(false);
    });
  });

  describe('State Isolation', () => {
    it('maintains separate state for different properties', async () => {
      const { setHighlightedConcepts, setLastQuery, updateMastery } = useAppStore.getState();

      fetchMock.mockResolvedValueOnce(masteryResponse('Test', 0.45));

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
