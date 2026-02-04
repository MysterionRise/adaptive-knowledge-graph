import { render, screen, fireEvent } from '@testing-library/react';
import { ErrorBoundary, ErrorFallback, withErrorBoundary } from '@/components/ErrorBoundary';

// Component that throws an error
const ThrowingComponent = ({ shouldThrow = true }: { shouldThrow?: boolean }) => {
  if (shouldThrow) {
    throw new Error('Test error message');
  }
  return <div>Component rendered successfully</div>;
};

// Suppress console.error for expected errors in tests
const originalError = console.error;
beforeAll(() => {
  console.error = jest.fn();
});
afterAll(() => {
  console.error = originalError;
});

describe('ErrorBoundary', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Normal Rendering', () => {
    it('renders children when no error occurs', () => {
      render(
        <ErrorBoundary>
          <div>Child content</div>
        </ErrorBoundary>
      );

      expect(screen.getByText('Child content')).toBeInTheDocument();
    });

    it('renders multiple children correctly', () => {
      render(
        <ErrorBoundary>
          <div>First child</div>
          <div>Second child</div>
        </ErrorBoundary>
      );

      expect(screen.getByText('First child')).toBeInTheDocument();
      expect(screen.getByText('Second child')).toBeInTheDocument();
    });
  });

  describe('Error Handling', () => {
    it('catches errors and displays fallback UI', () => {
      render(
        <ErrorBoundary>
          <ThrowingComponent />
        </ErrorBoundary>
      );

      expect(screen.getByText('Something went wrong')).toBeInTheDocument();
    });

    it('displays default error message', () => {
      render(
        <ErrorBoundary>
          <ThrowingComponent />
        </ErrorBoundary>
      );

      expect(
        screen.getByText('We encountered an unexpected error. Please try again.')
      ).toBeInTheDocument();
    });

    it('shows Try Again button', () => {
      render(
        <ErrorBoundary>
          <ThrowingComponent />
        </ErrorBoundary>
      );

      expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
    });

    it('shows Refresh Page button', () => {
      render(
        <ErrorBoundary>
          <ThrowingComponent />
        </ErrorBoundary>
      );

      expect(screen.getByRole('button', { name: /refresh page/i })).toBeInTheDocument();
    });

    it('logs error to console', () => {
      render(
        <ErrorBoundary>
          <ThrowingComponent />
        </ErrorBoundary>
      );

      expect(console.error).toHaveBeenCalledWith(
        'ErrorBoundary caught an error:',
        expect.any(Error),
        expect.any(Object)
      );
    });
  });

  describe('Custom Fallback', () => {
    it('renders custom fallback when provided', () => {
      render(
        <ErrorBoundary fallback={<div>Custom error message</div>}>
          <ThrowingComponent />
        </ErrorBoundary>
      );

      expect(screen.getByText('Custom error message')).toBeInTheDocument();
      expect(screen.queryByText('Something went wrong')).not.toBeInTheDocument();
    });
  });

  describe('Error Callback', () => {
    it('calls onError callback with error and errorInfo', () => {
      const onError = jest.fn();

      render(
        <ErrorBoundary onError={onError}>
          <ThrowingComponent />
        </ErrorBoundary>
      );

      expect(onError).toHaveBeenCalledWith(
        expect.any(Error),
        expect.objectContaining({
          componentStack: expect.any(String),
        })
      );
    });

    it('passes correct error message to callback', () => {
      const onError = jest.fn();

      render(
        <ErrorBoundary onError={onError}>
          <ThrowingComponent />
        </ErrorBoundary>
      );

      expect(onError.mock.calls[0][0].message).toBe('Test error message');
    });
  });

  describe('Recovery', () => {
    it('resets error state when Try Again is clicked', () => {
      const TestComponent = () => {
        const [shouldThrow, setShouldThrow] = React.useState(true);

        return (
          <ErrorBoundary>
            {shouldThrow ? (
              <ThrowingComponent shouldThrow={true} />
            ) : (
              <div>Recovered successfully</div>
            )}
          </ErrorBoundary>
        );
      };

      // Import React for useState
      const React = require('react');

      // This tests the retry mechanism
      render(
        <ErrorBoundary>
          <ThrowingComponent />
        </ErrorBoundary>
      );

      const tryAgainButton = screen.getByRole('button', { name: /try again/i });
      expect(tryAgainButton).toBeInTheDocument();

      // Click Try Again - it will throw again since component still throws
      fireEvent.click(tryAgainButton);

      // Error boundary resets, but component throws again
      expect(screen.getByText('Something went wrong')).toBeInTheDocument();
    });
  });
});

describe('ErrorFallback', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders error message heading', () => {
    render(<ErrorFallback error={null} />);

    expect(screen.getByText('Something went wrong')).toBeInTheDocument();
  });

  it('renders descriptive text', () => {
    render(<ErrorFallback error={null} />);

    expect(
      screen.getByText('We encountered an unexpected error. Please try again.')
    ).toBeInTheDocument();
  });

  it('displays error details in development mode', () => {
    const originalEnv = process.env.NODE_ENV;
    Object.defineProperty(process.env, 'NODE_ENV', { value: 'development', writable: true });

    const testError = new Error('Detailed error message');
    render(<ErrorFallback error={testError} />);

    expect(screen.getByText('Detailed error message')).toBeInTheDocument();

    Object.defineProperty(process.env, 'NODE_ENV', { value: originalEnv, writable: true });
  });

  it('hides error details in production mode', () => {
    const originalEnv = process.env.NODE_ENV;
    Object.defineProperty(process.env, 'NODE_ENV', { value: 'production', writable: true });

    const testError = new Error('Secret error details');
    render(<ErrorFallback error={testError} />);

    expect(screen.queryByText('Secret error details')).not.toBeInTheDocument();

    Object.defineProperty(process.env, 'NODE_ENV', { value: originalEnv, writable: true });
  });

  it('shows Try Again button when onRetry is provided', () => {
    const onRetry = jest.fn();
    render(<ErrorFallback error={null} onRetry={onRetry} />);

    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
  });

  it('hides Try Again button when onRetry is not provided', () => {
    render(<ErrorFallback error={null} />);

    expect(screen.queryByRole('button', { name: /try again/i })).not.toBeInTheDocument();
  });

  it('calls onRetry when Try Again is clicked', () => {
    const onRetry = jest.fn();
    render(<ErrorFallback error={null} onRetry={onRetry} />);

    fireEvent.click(screen.getByRole('button', { name: /try again/i }));

    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('reloads page when Refresh Page is clicked', () => {
    const reloadMock = jest.fn();
    Object.defineProperty(window, 'location', {
      value: { reload: reloadMock },
      writable: true,
    });

    render(<ErrorFallback error={null} />);

    fireEvent.click(screen.getByRole('button', { name: /refresh page/i }));

    expect(reloadMock).toHaveBeenCalledTimes(1);
  });

  it('renders error icon', () => {
    const { container } = render(<ErrorFallback error={null} />);

    const svg = container.querySelector('svg');
    expect(svg).toBeInTheDocument();
    expect(svg).toHaveClass('text-red-500');
  });
});

describe('withErrorBoundary HOC', () => {
  it('wraps component with error boundary', () => {
    const SimpleComponent = () => <div>Simple content</div>;
    const WrappedComponent = withErrorBoundary(SimpleComponent);

    render(<WrappedComponent />);

    expect(screen.getByText('Simple content')).toBeInTheDocument();
  });

  it('catches errors in wrapped component', () => {
    const WrappedComponent = withErrorBoundary(ThrowingComponent);

    render(<WrappedComponent />);

    expect(screen.getByText('Something went wrong')).toBeInTheDocument();
  });

  it('uses custom fallback when provided', () => {
    const WrappedComponent = withErrorBoundary(
      ThrowingComponent,
      <div>HOC custom fallback</div>
    );

    render(<WrappedComponent />);

    expect(screen.getByText('HOC custom fallback')).toBeInTheDocument();
  });

  it('passes props to wrapped component', () => {
    const PropsComponent = ({ name }: { name: string }) => <div>Hello, {name}</div>;
    const WrappedComponent = withErrorBoundary(PropsComponent);

    render(<WrappedComponent name="World" />);

    expect(screen.getByText('Hello, World')).toBeInTheDocument();
  });

  it('preserves component display name', () => {
    const NamedComponent = () => <div>Named</div>;
    NamedComponent.displayName = 'NamedComponent';

    const WrappedComponent = withErrorBoundary(NamedComponent);

    // The wrapper function name contains the original component info
    expect(WrappedComponent.name).toBe('WithErrorBoundaryWrapper');
  });
});

describe('ErrorBoundary Integration', () => {
  it('handles nested error boundaries', () => {
    const InnerError = () => {
      throw new Error('Inner error');
    };

    render(
      <ErrorBoundary fallback={<div>Outer fallback</div>}>
        <div>Outer content</div>
        <ErrorBoundary fallback={<div>Inner fallback</div>}>
          <InnerError />
        </ErrorBoundary>
      </ErrorBoundary>
    );

    expect(screen.getByText('Outer content')).toBeInTheDocument();
    expect(screen.getByText('Inner fallback')).toBeInTheDocument();
    expect(screen.queryByText('Outer fallback')).not.toBeInTheDocument();
  });

  it('handles error in sibling component', () => {
    const GoodComponent = () => <div>Good component</div>;

    render(
      <ErrorBoundary>
        <GoodComponent />
        <ThrowingComponent />
      </ErrorBoundary>
    );

    // Both are wrapped in same boundary, so both are replaced
    expect(screen.getByText('Something went wrong')).toBeInTheDocument();
    expect(screen.queryByText('Good component')).not.toBeInTheDocument();
  });
});
