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
    llm_ready: true,
    openstax_subject_seeded: true,
    latest_eval_valid: true,
  },
  next_actions: [],
};

/** The value shown next to a term of the "Latest Evaluation" list. */
const valueOf = (term: string) => screen.getByText(term).nextSibling;

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
    expect(screen.getByText('The services, the seeded OpenStax data, the language model and the latest eval are ready for rehearsal.')).toBeInTheDocument();
  });

  it('renders the latest evaluation provenance and validity signals', async () => {
    (apiClient.getDemoStatus as jest.Mock).mockResolvedValue({
      ...readyStatus,
      latest_eval: {
        ...readyStatus.latest_eval,
        kg_expansion_failures: 0,
        prompt_injection_resistance_rate: 0.75,
        has_provenance: true,
        git_sha: '0123456789abcdef0123',
        golden_set_sha256: 'fedcba9876543210fedc',
      },
    });

    render(<DemoStatusPage />);

    await screen.findByText('Demo ready');
    expect(valueOf('KG expansion failures')).toHaveTextContent('0');
    expect(screen.getByText('75%')).toBeInTheDocument();
    expect(
      screen.getByText('Server 0123456789ab, golden set fedcba987654')
    ).toBeInTheDocument();
  });

  it('renders the evaluation deltas and the refusal rate', async () => {
    (apiClient.getDemoStatus as jest.Mock).mockResolvedValue({
      ...readyStatus,
      latest_eval: {
        ...readyStatus.latest_eval,
        citation_hit_rate_delta: 0.125,
        mrr_delta: 0.0831,
        unsupported_refusal_rate: 0.85,
      },
    });

    render(<DemoStatusPage />);

    await screen.findByText('Demo ready');
    expect(valueOf('Citation hit rate Δ (KG − plain)')).toHaveTextContent('+12.5 pp');
    expect(valueOf('MRR Δ (KG − plain)')).toHaveTextContent('+0.083');
    expect(valueOf('Unsupported-question refusal rate')).toHaveTextContent('85%');
  });

  it('shows a negative citation delta with its sign', async () => {
    (apiClient.getDemoStatus as jest.Mock).mockResolvedValue({
      ...readyStatus,
      latest_eval: { ...readyStatus.latest_eval, citation_hit_rate_delta: -0.03, mrr_delta: -0.0125 },
    });

    render(<DemoStatusPage />);

    await screen.findByText('Demo ready');
    expect(valueOf('Citation hit rate Δ (KG − plain)')).toHaveTextContent('-3.0 pp');
    expect(valueOf('MRR Δ (KG − plain)')).toHaveTextContent('-0.013');
  });

  it('shows a placeholder for the metrics the report does not have', async () => {
    (apiClient.getDemoStatus as jest.Mock).mockResolvedValue(readyStatus);

    render(<DemoStatusPage />);

    await screen.findByText('Demo ready');
    for (const term of [
      'Citation hit rate Δ (KG − plain)',
      'MRR Δ (KG − plain)',
      'Unsupported-question refusal rate',
      'Prompt-injection resistance',
      'KG expansion failures',
    ]) {
      expect(valueOf(term)).toHaveTextContent('—');
    }
    expect(screen.queryByText('n/a')).not.toBeInTheDocument();
  });

  it('flags a latest evaluation without provenance', async () => {
    (apiClient.getDemoStatus as jest.Mock).mockResolvedValue(readyStatus);

    render(<DemoStatusPage />);

    await screen.findByText('Demo ready');
    expect(valueOf('Provenance')).toHaveTextContent('Missing');
    expect(valueOf('Prompt-injection resistance')).toHaveTextContent('—');
  });

  it('lists the script readiness checks', async () => {
    (apiClient.getDemoStatus as jest.Mock).mockResolvedValue({
      ...readyStatus,
      script_readiness: { ...readyStatus.script_readiness, latest_eval_valid: false },
    });

    render(<DemoStatusPage />);

    await screen.findByText('Demo ready');
    const heading = screen.getByRole('heading', { level: 2, name: 'Script Readiness' });
    const card = heading.closest('div.rounded-lg') as HTMLElement;
    const items = within(card).getAllByRole('listitem');
    expect(items.map((item) => item.textContent)).toEqual([
      'Critical services (Neo4j, OpenSearch)Ready',
      'Language model configuredReady',
      'OpenStax subject seededReady',
      'Latest evaluation validNot ready',
    ]);
  });

  it('labels the readiness checks of older servers and unknown keys', async () => {
    (apiClient.getDemoStatus as jest.Mock).mockResolvedValue({
      ...readyStatus,
      script_readiness: { local_llm_ready: true, golden_set_fresh: false },
    });

    render(<DemoStatusPage />);

    await screen.findByText('Demo ready');
    expect(screen.getByText('Local LLM (Ollama)')).toBeInTheDocument();
    expect(screen.getByText('Golden set fresh')).toBeInTheDocument();
  });

  it('labels the language model service card', async () => {
    (apiClient.getDemoStatus as jest.Mock).mockResolvedValue({
      ...readyStatus,
      services: {
        ...readyStatus.services,
        ollama: { status: 'ok', message: 'OpenRouter model: anthropic/claude-sonnet-4' },
      },
    });

    render(<DemoStatusPage />);

    await screen.findByText('Demo ready');
    expect(screen.getByRole('heading', { level: 3, name: 'Language model' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { level: 3, name: 'ollama' })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 3, name: 'Neo4j' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 3, name: 'OpenSearch' })).toBeInTheDocument();
    expect(screen.getByText('OpenRouter model: anthropic/claude-sonnet-4')).toBeInTheDocument();
  });

  it('shows a configured subject without concepts as not seeded, not as a warning', async () => {
    (apiClient.getDemoStatus as jest.Mock).mockResolvedValue({
      ...readyStatus,
      subjects: [
        ...readyStatus.subjects,
        {
          id: 'biology',
          name: 'Biology',
          status: 'degraded',
          concept_count: 0,
          module_count: 0,
          relationship_count: 0,
          message: 'Configured, but no graph concepts were found.',
        },
      ],
    });

    render(<DemoStatusPage />);

    const row = (await screen.findByText('Biology')).closest('tr') as HTMLElement;
    expect(within(row).getByText('Not seeded')).toHaveAttribute(
      'title',
      'Configured, but no graph concepts were found.'
    );
    expect(screen.queryByText('Needs attention')).not.toBeInTheDocument();
    const seeded = screen.getByText('US History').closest('tr') as HTMLElement;
    expect(within(seeded).getByText('Ready')).toBeInTheDocument();
  });

  it('keeps the warning for a degraded subject that has concepts', async () => {
    (apiClient.getDemoStatus as jest.Mock).mockResolvedValue({
      ...readyStatus,
      subjects: [{ ...readyStatus.subjects[0], status: 'degraded' }],
    });

    render(<DemoStatusPage />);

    const row = (await screen.findByText('US History')).closest('tr') as HTMLElement;
    expect(within(row).getByText('Needs attention')).toBeInTheDocument();
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
