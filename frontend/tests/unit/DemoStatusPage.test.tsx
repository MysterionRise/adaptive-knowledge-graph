import { render, screen, waitFor } from '@testing-library/react';
import DemoStatusPage from '@/app/demo-status/page';
import { apiClient } from '@/lib/api-client';

jest.mock('@/lib/api-client', () => ({
  apiClient: {
    getDemoStatus: jest.fn(),
  },
}));

jest.mock('next/link', () => {
  return ({ children, href }: any) => <a href={href}>{children}</a>;
});

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

  it('renders an API failure message', async () => {
    (apiClient.getDemoStatus as jest.Mock).mockRejectedValue(new Error('Network error'));

    render(<DemoStatusPage />);

    await waitFor(() => {
      expect(screen.getByText(/Unable to load demo readiness/i)).toBeInTheDocument();
    });
  });
});
