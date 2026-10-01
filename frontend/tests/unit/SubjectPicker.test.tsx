import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import SubjectPicker from '@/components/SubjectPicker';
import { ApiError } from '@/lib/api-errors';
import { useAppStore } from '@/lib/store';

// Mock lucide-react icons
jest.mock('lucide-react', () => ({
  ChevronDown: ({ className }: any) => <span data-testid="chevron-down" className={className} />,
  BookOpen: ({ className }: any) => <span data-testid="book-open" className={className} />,
  RefreshCw: ({ className }: any) => <span data-testid="refresh" className={className} />,
}));

// Mock api-client
jest.mock('@/lib/api-client', () => ({
  apiClient: {
    getSubjects: jest.fn(),
  },
}));

import { apiClient } from '@/lib/api-client';

const mockGetSubjects = apiClient.getSubjects as jest.Mock;

const mockSubjects = {
  subjects: [
    { id: 'us_history', name: 'US History', description: 'American history', is_default: true, available: true },
    // Older backends do not send `available`
    { id: 'economics', name: 'Economics', description: 'Economic principles', is_default: false },
    { id: 'biology', name: 'Biology', description: 'Life sciences', is_default: false, available: false },
    { id: 'world_history', name: 'World History', description: 'World history', is_default: false, available: true },
  ],
  default_subject: 'us_history',
};

// Reset store between tests
const initialStoreState = useAppStore.getState();

const trigger = () => screen.getByRole('button', { name: /Subject:/ });
const option = (name: RegExp) => screen.getByRole('option', { name });

/** Render the picker and wait for the subjects. */
async function renderPicker() {
  render(<SubjectPicker />);
  await screen.findByRole('button', { name: /Subject:/ });
}

describe('SubjectPicker Component', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useAppStore.setState(initialStoreState);
    mockGetSubjects.mockResolvedValue(mockSubjects);
  });

  describe('Loading State', () => {
    it('shows loading skeleton while fetching subjects', () => {
      mockGetSubjects.mockImplementation(() => new Promise(() => {}));

      render(<SubjectPicker />);

      expect(screen.getByRole('status')).toHaveTextContent('Loading subjects');
      expect(document.querySelector('.animate-pulse')).toBeInTheDocument();
    });
  });

  describe('Rendered State', () => {
    it('shows the current subject in the button', async () => {
      useAppStore.setState({ currentSubject: 'economics' });

      await renderPicker();

      expect(trigger()).toHaveAccessibleName('Subject: Economics');
      expect(trigger()).toHaveAttribute('aria-haspopup', 'listbox');
      expect(trigger()).toHaveAttribute('aria-expanded', 'false');
    });

    it('switches to the default subject when the remembered one no longer exists', async () => {
      useAppStore.setState({ currentSubject: 'nonexistent' });

      await renderPicker();

      await waitFor(() => expect(useAppStore.getState().currentSubject).toBe('us_history'));
      expect(trigger()).toHaveAccessibleName('Subject: US History');
    });

    it('switches to the default subject when the remembered one has no data', async () => {
      useAppStore.setState({ currentSubject: 'biology' });

      await renderPicker();

      await waitFor(() => expect(useAppStore.getState().currentSubject).toBe('us_history'));
    });

    it('keeps the subject when no subject has data (e.g. the database is down)', async () => {
      mockGetSubjects.mockResolvedValue({
        ...mockSubjects,
        subjects: mockSubjects.subjects.map((subject) => ({ ...subject, available: false })),
      });
      useAppStore.setState({ currentSubject: 'economics' });

      await renderPicker();

      expect(useAppStore.getState().currentSubject).toBe('economics');
    });

    it('uses the theme colour of the current subject', async () => {
      useAppStore.setState({
        subjectTheme: {
          subject_id: 'us_history',
          primary_color: '#dc2626',
          secondary_color: '#fca5a5',
          accent_color: '#b91c1c',
          chapter_colors: {},
        },
      });

      await renderPicker();

      expect(trigger().firstElementChild).toHaveStyle({ backgroundColor: '#dc2626' });
    });

    it('uses a neutral colour until the theme of the subject is loaded', async () => {
      await renderPicker();

      expect(trigger().firstElementChild).toHaveStyle({ backgroundColor: '#9ca3af' });
    });
  });

  describe('Dropdown Interaction', () => {
    it('opens a listbox with all subjects', async () => {
      await renderPicker();

      fireEvent.click(trigger());

      expect(trigger()).toHaveAttribute('aria-expanded', 'true');
      const listbox = screen.getByRole('listbox', { name: 'Subjects' });
      expect(trigger()).toHaveAttribute('aria-controls', listbox.id);
      expect(screen.getAllByRole('option')).toHaveLength(4);
      expect(option(/US History/)).toHaveAttribute('aria-selected', 'true');
      expect(option(/Economics/)).toHaveAttribute('aria-selected', 'false');
    });

    it('marks the default subject', async () => {
      await renderPicker();
      fireEvent.click(trigger());

      expect(option(/US History/)).toHaveTextContent('Default');
    });

    it('shows subjects without data as disabled "coming soon" options', async () => {
      await renderPicker();
      fireEvent.click(trigger());

      expect(option(/Biology/)).toHaveAttribute('aria-disabled', 'true');
      expect(option(/Biology/)).toHaveTextContent('Coming soon');
      // A missing `available` field means the subject can be selected
      expect(option(/Economics/)).not.toHaveAttribute('aria-disabled');
      expect(option(/Economics/)).not.toHaveTextContent('Coming soon');

      fireEvent.click(option(/Biology/));

      expect(useAppStore.getState().currentSubject).toBe('us_history');
      expect(screen.getByRole('listbox')).toBeInTheDocument();
    });

    it('changes the subject when an option is clicked', async () => {
      await renderPicker();
      fireEvent.click(trigger());

      fireEvent.click(option(/Economics/));

      expect(useAppStore.getState().currentSubject).toBe('economics');
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
      expect(trigger()).toHaveAccessibleName('Subject: Economics');
      expect(trigger()).toHaveFocus();
    });

    it('closes the dropdown when the backdrop is clicked', async () => {
      await renderPicker();
      fireEvent.click(trigger());

      fireEvent.click(document.querySelector('.fixed.inset-0') as Element);

      expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    });

    it('closes the dropdown when the button is clicked again', async () => {
      await renderPicker();
      fireEvent.click(trigger());

      fireEvent.click(trigger());

      expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    });
  });

  describe('Keyboard', () => {
    it('opens with ArrowDown and focuses the selected subject', async () => {
      useAppStore.setState({ currentSubject: 'economics' });
      await renderPicker();

      fireEvent.keyDown(trigger(), { key: 'ArrowDown' });

      expect(option(/Economics/)).toHaveFocus();
    });

    it('opens with ArrowUp and focuses the last available subject', async () => {
      await renderPicker();

      fireEvent.keyDown(trigger(), { key: 'ArrowUp' });

      expect(option(/World History/)).toHaveFocus();
    });

    it('moves between available subjects, skipping disabled ones', async () => {
      await renderPicker();
      fireEvent.keyDown(trigger(), { key: 'ArrowDown' });
      const listbox = screen.getByRole('listbox');

      fireEvent.keyDown(listbox, { key: 'ArrowDown' });
      expect(option(/Economics/)).toHaveFocus();

      fireEvent.keyDown(listbox, { key: 'ArrowDown' });
      expect(option(/World History/)).toHaveFocus();

      // Stays on the last option
      fireEvent.keyDown(listbox, { key: 'ArrowDown' });
      expect(option(/World History/)).toHaveFocus();

      fireEvent.keyDown(listbox, { key: 'ArrowUp' });
      expect(option(/Economics/)).toHaveFocus();

      fireEvent.keyDown(listbox, { key: 'Home' });
      expect(option(/US History/)).toHaveFocus();

      fireEvent.keyDown(listbox, { key: 'End' });
      expect(option(/World History/)).toHaveFocus();
    });

    it('selects the focused subject with Enter', async () => {
      await renderPicker();
      fireEvent.keyDown(trigger(), { key: 'ArrowDown' });
      fireEvent.keyDown(screen.getByRole('listbox'), { key: 'ArrowDown' });

      fireEvent.keyDown(screen.getByRole('listbox'), { key: 'Enter' });

      expect(useAppStore.getState().currentSubject).toBe('economics');
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
      expect(trigger()).toHaveFocus();
    });

    it('selects the focused subject with Space', async () => {
      await renderPicker();
      fireEvent.keyDown(trigger(), { key: 'ArrowUp' });

      fireEvent.keyDown(screen.getByRole('listbox'), { key: ' ' });

      expect(useAppStore.getState().currentSubject).toBe('world_history');
    });

    it('closes with Escape and returns focus to the button', async () => {
      await renderPicker();
      fireEvent.keyDown(trigger(), { key: 'ArrowDown' });

      fireEvent.keyDown(screen.getByRole('listbox'), { key: 'Escape' });

      expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
      expect(trigger()).toHaveFocus();
      expect(useAppStore.getState().currentSubject).toBe('us_history');
    });

    it('closes when focus leaves with Tab', async () => {
      await renderPicker();
      fireEvent.keyDown(trigger(), { key: 'ArrowDown' });

      fireEvent.keyDown(screen.getByRole('listbox'), { key: 'Tab' });

      expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    });
  });

  describe('Error Handling', () => {
    it('shows an error with a retry action instead of an empty dropdown', async () => {
      mockGetSubjects
        .mockRejectedValueOnce(new ApiError('network', 'Could not reach the API at http://localhost:8000.'))
        .mockResolvedValueOnce(mockSubjects);

      render(<SubjectPicker />);

      const alert = await screen.findByRole('alert');
      expect(alert).toHaveTextContent("Couldn't load subjects");
      expect(alert).toHaveTextContent('Could not reach the API at http://localhost:8000.');
      expect(screen.queryByRole('button', { name: /Subject:/ })).not.toBeInTheDocument();

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
      });

      expect(await screen.findByRole('button', { name: /Subject:/ })).toBeInTheDocument();
      expect(mockGetSubjects).toHaveBeenCalledTimes(2);
    });
  });
});
