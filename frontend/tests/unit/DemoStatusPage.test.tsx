import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import DemoStatusPage from '@/app/demo-status/page';
import { apiClient } from '@/lib/api-client';
import { ApiError } from '@/lib/api-errors';

jest.mock('@/lib/api-client', () => ({
  apiClient: {
    getDemoStatus: jest.fn(),
  },
}));

const readyStatus = {
  status: 'ready',
  positioning: 'Controlled local OpenStax client demo; not production certification infrastructure.',
  services: {
    neo4j: { status: 'ok', latency_ms: 12.3 },
    opensearch: { status: 'ok', latency_ms: 8.1 },
    ollama: { status: 'ok', latency_ms: 20.4 },
  },
  subjects: [
    {
      id: 'us_history',
      name: 'US History',
      status: 'ok',
      concept_count: 100,
      module_count: 10,
      relationship_count: 200,
    },
  ],
  latest_eval: {
    status: 'ok',
    environment_valid: true,
    cases: 50,
    kg_successful_cases: 50,
    plain_successful_cases: 50,
  },
  script_readiness: {
    critical_services_ready: true,
    local_llm_ready: true,
    openstax_subject_seeded: true,
    latest_eval_valid: true,
  },
  next_actions: [],
};

describe('DemoStatusPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders ready demo status', async () => {
    (apiClient.getDemoStatus as jest.Mock).mockResolvedValue(readyStatus);

    render(<DemoStatusPage />);

    await waitFor(() => {
      expect(screen.getByText('Demo ready')).toBeInTheDocument();
    });
    expect(screen.getByText('US History')).toBeInTheDocument();
    expect(screen.getByText('The local stack, seeded OpenStax data, local LLM, and latest eval are ready for rehearsal.')).toBeInTheDocument();
  });

  it('renders next actions when demo is degraded', async () => {
    (apiClient.getDemoStatus as jest.Mock).mockResolvedValue({
      ...readyStatus,
      status: 'degraded',
      latest_eval: {
        ...readyStatus.latest_eval,
        status: 'error',
        environment_valid: false,
        message: 'Latest eval is missing successful live KG/plain cases.',
      },
      next_actions: ['Run make demo-eval after the API and demo data are available.'],
    });

    render(<DemoStatusPage />);

    await waitFor(() => {
      expect(screen.getByText('Rehearsal required')).toBeInTheDocument();
    });
    expect(screen.getByText('Run make demo-eval after the API and demo data are available.')).toBeInTheDocument();
  });

  it('renders the page heading and a neutral description', async () => {
    (apiClient.getDemoStatus as jest.Mock).mockResolvedValue(readyStatus);

    render(<DemoStatusPage />);

    await screen.findByText('Demo ready');
    const header = screen.getByRole('banner');
    expect(within(header).getByRole('heading', { level: 1, name: 'Demo Status' })).toBeInTheDocument();
    expect(header).not.toHaveTextContent(/client|walkthrough/i);
  });

  it('shows the loading state', () => {
    (apiClient.getDemoStatus as jest.Mock).mockImplementation(() => new Promise(() => {}));

    render(<DemoStatusPage />);

    expect(screen.getByRole('status')).toHaveTextContent('Loading demo readiness...');
    expect(screen.getByRole('button', { name: 'Refresh' })).toBeDisabled();
  });

  it('renders an API failure message with the backend detail', async () => {
    (apiClient.getDemoStatus as jest.Mock).mockRejectedValue(
      new ApiError('http', 'Bad gateway', { status: 502 })
    );

    render(<DemoStatusPage />);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Unable to load demo readiness.');
    expect(alert).toHaveTextContent('Bad gateway');
  });

  it('loads the report again on retry', async () => {
    (apiClient.getDemoStatus as jest.Mock)
      .mockRejectedValueOnce(new ApiError('network', 'Could not reach the API'))
      .mockResolvedValueOnce(readyStatus);

    render(<DemoStatusPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Retry' }));

    expect(await screen.findByText('Demo ready')).toBeInTheDocument();
    expect(apiClient.getDemoStatus).toHaveBeenCalledTimes(2);
  });

  it('keeps the report visible while it refreshes', async () => {
    (apiClient.getDemoStatus as jest.Mock)
      .mockResolvedValueOnce(readyStatus)
      .mockImplementationOnce(() => new Promise(() => {}));

    render(<DemoStatusPage />);
    await screen.findByText('Demo ready');

    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));

    expect(screen.getByText('Demo ready')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Refresh' })).toBeDisabled();
  });
});
