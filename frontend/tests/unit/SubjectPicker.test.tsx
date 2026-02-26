import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import SubjectPicker from '@/components/SubjectPicker';
import { useAppStore } from '@/lib/store';

// Mock lucide-react icons
jest.mock('lucide-react', () => ({
  ChevronDown: ({ className }: any) => <span data-testid="chevron-down" className={className} />,
  BookOpen: ({ className }: any) => <span data-testid="book-open" className={className} />,
}));

// Mock api-client
jest.mock('@/lib/api-client', () => ({
  apiClient: {
    getSubjects: jest.fn(),
  },
}));

import { apiClient } from '@/lib/api-client';

const mockSubjects = {
  subjects: [
    { id: 'us_history', name: 'US History', description: 'American history', is_default: true },
    { id: 'economics', name: 'Economics', description: 'Economic principles', is_default: false },
    { id: 'biology', name: 'Biology', description: 'Life sciences', is_default: false },
  ],
  default_subject: 'us_history',
};

// Reset store between tests
const initialStoreState = useAppStore.getState();

describe('SubjectPicker Component', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useAppStore.setState(initialStoreState);
    (apiClient.getSubjects as jest.Mock).mockResolvedValue(mockSubjects);
  });

  describe('Loading State', () => {
    it('shows loading skeleton while fetching subjects', () => {
      (apiClient.getSubjects as jest.Mock).mockImplementation(
        () => new Promise(() => {}) // Never resolves
      );

      render(<SubjectPicker />);

      expect(screen.getByText('', { selector: '.animate-pulse' })).toBeInTheDocument();
    });
  });

  describe('Rendered State', () => {
    it('renders subject picker button after loading', async () => {
      render(<SubjectPicker />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /Select Subject|US History/i })).toBeInTheDocument();
      });
    });

    it('shows current subject name in button', async () => {
      useAppStore.setState({ currentSubject: 'us_history' });

      render(<SubjectPicker />);

      await waitFor(() => {
        expect(screen.getByText('US History')).toBeInTheDocument();
      });
    });

    it('shows "Select Subject" when no match found', async () => {
      useAppStore.setState({ currentSubject: 'nonexistent' });

      render(<SubjectPicker />);

      await waitFor(() => {
        expect(screen.getByText('Select Subject')).toBeInTheDocument();
      });
    });
  });

  describe('Dropdown Interaction', () => {
    it('opens dropdown when button is clicked', async () => {
      render(<SubjectPicker />);

      await waitFor(() => {
        expect(screen.getByText('US History')).toBeInTheDocument();
      });

      const button = screen.getByRole('button', { name: /US History/i });
      fireEvent.click(button);

      // All subjects should be visible in dropdown
      expect(screen.getByText('Economics')).toBeInTheDocument();
      expect(screen.getByText('Biology')).toBeInTheDocument();
    });

    it('shows default badge on default subject', async () => {
      render(<SubjectPicker />);

      await waitFor(() => {
        expect(screen.getByText('US History')).toBeInTheDocument();
      });

      const button = screen.getByRole('button', { name: /US History/i });
      fireEvent.click(button);

      expect(screen.getByText('Default')).toBeInTheDocument();
    });

    it('closes dropdown when backdrop is clicked', async () => {
      render(<SubjectPicker />);

      await waitFor(() => {
        expect(screen.getByText('US History')).toBeInTheDocument();
      });

      const button = screen.getByRole('button', { name: /US History/i });
      fireEvent.click(button);

      // Economics should be visible
      expect(screen.getByText('Economics')).toBeInTheDocument();

      // Click backdrop (fixed inset-0 div)
      const backdrop = document.querySelector('.fixed.inset-0');
      if (backdrop) {
        fireEvent.click(backdrop);
      }

      // Dropdown should close — Economics should no longer be an option
      await waitFor(() => {
        // The button text "US History" should still be there but dropdown options gone
        const options = screen.queryAllByRole('option');
        expect(options.length).toBe(0);
      });
    });

    it('changes subject when option is clicked', async () => {
      // Mock the theme fetch
      global.fetch = jest.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          subject_id: 'economics',
          primary_color: '#d97706',
          secondary_color: '#fbbf24',
          accent_color: '#f59e0b',
          chapter_colors: {},
        }),
      });

      render(<SubjectPicker />);

      await waitFor(() => {
        expect(screen.getByText('US History')).toBeInTheDocument();
      });

      const button = screen.getByRole('button', { name: /US History/i });
      fireEvent.click(button);

      // Click Economics
      const economicsOption = screen.getByRole('option', { name: /Economics/i });
      fireEvent.click(economicsOption);

      // Store should be updated
      expect(useAppStore.getState().currentSubject).toBe('economics');
    });
  });

  describe('Accessibility', () => {
    it('has aria-haspopup on trigger button', async () => {
      render(<SubjectPicker />);

      await waitFor(() => {
        const button = screen.getByRole('button', { name: /US History/i });
        expect(button).toHaveAttribute('aria-haspopup', 'listbox');
      });
    });

    it('has aria-expanded reflecting open state', async () => {
      render(<SubjectPicker />);

      await waitFor(() => {
        const button = screen.getByRole('button', { name: /US History/i });
        expect(button).toHaveAttribute('aria-expanded', 'false');

        fireEvent.click(button);
        expect(button).toHaveAttribute('aria-expanded', 'true');
      });
    });

    it('has aria-selected on current subject option', async () => {
      useAppStore.setState({ currentSubject: 'us_history' });

      render(<SubjectPicker />);

      await waitFor(() => {
        expect(screen.getByText('US History')).toBeInTheDocument();
      });

      const button = screen.getByRole('button', { name: /US History/i });
      fireEvent.click(button);

      const options = screen.getAllByRole('option');
      const selectedOption = options.find(
        (opt) => opt.getAttribute('aria-selected') === 'true'
      );
      expect(selectedOption).toBeTruthy();
    });
  });

  describe('Error Handling', () => {
    it('handles API failure gracefully', async () => {
      (apiClient.getSubjects as jest.Mock).mockRejectedValue(new Error('Network error'));

      render(<SubjectPicker />);

      // Should eventually render (loading state ends)
      await waitFor(() => {
        // Component should still render even if API fails
        expect(screen.getByRole('button')).toBeInTheDocument();
      });
    });
  });

  describe('Subject Color', () => {
    it('uses default color for known subjects', async () => {
      useAppStore.setState({ currentSubject: 'us_history' });

      render(<SubjectPicker />);

      await waitFor(() => {
        // The color dot should exist
        const colorDot = document.querySelector('.rounded-full');
        expect(colorDot).toBeInTheDocument();
      });
    });
  });
});
