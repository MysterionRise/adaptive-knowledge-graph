import { useAppStore } from '@/lib/store';

// Mock fetch
global.fetch = jest.fn();

describe('useAppStore', () => {
  beforeEach(() => {
    // Reset store to initial state
    useAppStore.setState({
      highlightedConcepts: [],
      lastQueryConcepts: [],
      lastQuery: null,
      masteryMap: {},
      isSyncing: false,
      lastSyncError: null,
      isGraphLoading: false,
    });
    jest.clearAllMocks();
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

  describe('Mastery Tracking', () => {
    it('initializes mastery for new concept', () => {
      const { getMastery } = useAppStore.getState();

      const mastery = getMastery('New Concept');

      expect(mastery).toBe(0.3); // Default initial mastery
    });

    it('updates mastery on correct answer', () => {
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          concept: 'Test Concept',
          previous_mastery: 0.3,
          new_mastery: 0.45,
          target_difficulty: 'medium',
          total_attempts: 1,
        }),
      });

      const { updateMastery, getMastery } = useAppStore.getState();

      updateMastery('Test Concept', true);

      // Local optimistic update
      const mastery = getMastery('Test Concept');
      expect(mastery).toBeCloseTo(0.45, 1); // 0.3 + 0.15 = 0.45
    });

    it('updates mastery on incorrect answer', () => {
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          concept: 'Test Concept',
          previous_mastery: 0.3,
          new_mastery: 0.2,
          target_difficulty: 'easy',
          total_attempts: 1,
        }),
      });

      const { updateMastery, getMastery } = useAppStore.getState();

      updateMastery('Test Concept', false);

      const mastery = getMastery('Test Concept');
      expect(mastery).toBeCloseTo(0.2, 1); // 0.3 - 0.1 = 0.2
    });

    it('clamps mastery to minimum 0.1', () => {
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          concept: 'Test Concept',
          previous_mastery: 0.1,
          new_mastery: 0.1,
          target_difficulty: 'easy',
          total_attempts: 1,
        }),
      });

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

      const mastery = getMastery('Low Concept');
      expect(mastery).toBeGreaterThanOrEqual(0.1);
    });

    it('clamps mastery to maximum 1.0', () => {
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          concept: 'Test Concept',
          previous_mastery: 0.95,
          new_mastery: 1.0,
          target_difficulty: 'hard',
          total_attempts: 1,
        }),
      });

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

      const mastery = getMastery('High Concept');
      expect(mastery).toBeLessThanOrEqual(1.0);
    });

    it('increments attempts counter', () => {
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          concept: 'Test Concept',
          previous_mastery: 0.3,
          new_mastery: 0.45,
          target_difficulty: 'medium',
          total_attempts: 1,
        }),
      });

      const { updateMastery } = useAppStore.getState();

      updateMastery('Attempt Concept', true);

      const { masteryMap } = useAppStore.getState();
      expect(masteryMap['Attempt Concept'].attempts).toBe(1);
    });

    it('sets lastAssessed timestamp', () => {
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          concept: 'Test Concept',
          previous_mastery: 0.3,
          new_mastery: 0.45,
          target_difficulty: 'medium',
          total_attempts: 1,
        }),
      });

      const { updateMastery } = useAppStore.getState();

      updateMastery('Timestamp Concept', true);

      const { masteryMap } = useAppStore.getState();
      expect(masteryMap['Timestamp Concept'].lastAssessed).not.toBeNull();
    });
  });

  describe('Backend Sync', () => {
    it('syncs mastery to backend on update', async () => {
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          concept: 'Sync Concept',
          previous_mastery: 0.3,
          new_mastery: 0.45,
          target_difficulty: 'medium',
          total_attempts: 1,
        }),
      });

      const { updateMastery } = useAppStore.getState();

      updateMastery('Sync Concept', true);

      // Wait for async sync
      await new Promise(resolve => setTimeout(resolve, 10));

      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/student/mastery'),
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ concept: 'Sync Concept', correct: true }),
        })
      );
    });

    it('handles sync errors gracefully', async () => {
      (global.fetch as jest.Mock).mockRejectedValueOnce(new Error('Network error'));

      const { syncMasteryToBackend } = useAppStore.getState();

      const result = await syncMasteryToBackend('Error Concept', true);

      expect(result).toBeNull();

      const { lastSyncError } = useAppStore.getState();
      expect(lastSyncError).toBe('Network error');
    });

    it('sets isSyncing during sync', async () => {
      (global.fetch as jest.Mock).mockImplementation(
        () =>
          new Promise((resolve) =>
            setTimeout(() =>
              resolve({
                ok: true,
                json: async () => ({
                  concept: 'Sync Concept',
                  previous_mastery: 0.3,
                  new_mastery: 0.45,
                  target_difficulty: 'medium',
                  total_attempts: 1,
                }),
              }),
            50
          )
        )
      );

      const { syncMasteryToBackend } = useAppStore.getState();

      const syncPromise = syncMasteryToBackend('Sync Concept', true);

      // Check isSyncing is true during sync
      const { isSyncing } = useAppStore.getState();
      expect(isSyncing).toBe(true);

      await syncPromise;

      const { isSyncing: isSyncingAfter } = useAppStore.getState();
      expect(isSyncingAfter).toBe(false);
    });
  });

  describe('Load Mastery from Backend', () => {
    it('loads mastery profile from backend', async () => {
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          student_id: 'test-student',
          overall_ability: 0.6,
          mastery_levels: {
            'Concept A': 0.8,
            'Concept B': 0.5,
          },
          updated_at: '2024-01-01T00:00:00Z',
        }),
      });

      const { loadMasteryFromBackend, getMastery } = useAppStore.getState();

      await loadMasteryFromBackend();

      expect(getMastery('Concept A')).toBe(0.8);
      expect(getMastery('Concept B')).toBe(0.5);
    });

    it('handles load errors gracefully', async () => {
      (global.fetch as jest.Mock).mockRejectedValueOnce(new Error('Load failed'));

      const { loadMasteryFromBackend } = useAppStore.getState();

      await loadMasteryFromBackend();

      const { lastSyncError } = useAppStore.getState();
      expect(lastSyncError).toBe('Load failed');
    });
  });

  describe('Reset Mastery', () => {
    it('resets mastery on backend', async () => {
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ message: 'Reset successful' }),
      });

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
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/student/reset'),
        expect.objectContaining({ method: 'POST' })
      );
    });

    it('handles reset errors gracefully', async () => {
      (global.fetch as jest.Mock).mockRejectedValueOnce(new Error('Reset failed'));

      const { resetMasteryOnBackend } = useAppStore.getState();

      await resetMasteryOnBackend();

      const { lastSyncError } = useAppStore.getState();
      expect(lastSyncError).toBe('Reset failed');
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
    it('maintains separate state for different properties', () => {
      const { setHighlightedConcepts, setLastQuery, updateMastery } =
        useAppStore.getState();

      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          concept: 'Test',
          previous_mastery: 0.3,
          new_mastery: 0.45,
          target_difficulty: 'medium',
          total_attempts: 1,
        }),
      });

      setHighlightedConcepts(['Concept']);
      setLastQuery('Query');
      updateMastery('Test', true);

      const state = useAppStore.getState();
      expect(state.highlightedConcepts).toEqual(['Concept']);
      expect(state.lastQuery).toBe('Query');
      expect(state.masteryMap['Test']).toBeDefined();
    });
  });
});
