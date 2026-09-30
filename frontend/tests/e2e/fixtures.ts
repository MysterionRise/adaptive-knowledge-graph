/**
 * Hermetic Playwright fixtures: every request to the backend API (`/api/v1/**`) is answered
 * from the stubs below, so the e2e suite runs without the FastAPI backend, Neo4j, OpenSearch or
 * an LLM. The default data describes the US History subject (the app's default subject).
 *
 * Tests can replace a single endpoint with `api.on('POST /ask', handler)` and inspect the
 * requests the page sent with `api.calls('POST /ask')`. Any request that has no stub fails the
 * test, as does any uncaught error in the page.
 */
import { test as base, expect, type Page, type Request, type Route } from '@playwright/test';

export { expect };

export interface StubResponse {
  status?: number;
  /** Serialized as JSON. */
  json?: unknown;
  /** Raw body, e.g. a server-sent-events stream. */
  body?: string;
  contentType?: string;
}

export type StubHandler = (request: Request) => StubResponse | Promise<StubResponse>;

// ---------------------------------------------------------------------------
// Stub data
// ---------------------------------------------------------------------------

export const subjects = {
  subjects: [
    {
      id: 'us_history',
      name: 'US History',
      description: 'American History from colonial times to modern era',
      is_default: true,
    },
    {
      id: 'economics',
      name: 'Economics',
      description: 'Principles of economics covering micro and macroeconomics',
      is_default: false,
    },
  ],
  default_subject: 'us_history',
};

export const graphStats: Record<string, { concept_count: number; module_count: number; relationship_count: number }> = {
  us_history: { concept_count: 128, module_count: 42, relationship_count: 356 },
  economics: { concept_count: 87, module_count: 31, relationship_count: 204 },
};

export const topConcepts = [
  { name: 'American Revolution', score: 0.95 },
  { name: 'Constitution', score: 0.9 },
  { name: 'Civil War', score: 0.88 },
];

export const graphData = {
  nodes: [
    { data: { id: 'c1', label: 'Colonial America', importance: 0.7, chapter: 'Colonial' } },
    { data: { id: 'c2', label: 'American Revolution', importance: 0.95, chapter: 'Revolution' } },
    { data: { id: 'c3', label: 'Declaration of Independence', importance: 0.8, chapter: 'Revolution' } },
    { data: { id: 'c4', label: 'Constitution', importance: 0.9, chapter: 'Constitution' } },
  ],
  edges: [
    { data: { id: 'e1', source: 'c1', target: 'c2', type: 'PREREQ', label: 'PREREQ' } },
    { data: { id: 'e2', source: 'c2', target: 'c3', type: 'COVERS', label: 'COVERS' } },
    { data: { id: 'e3', source: 'c2', target: 'c4', type: 'RELATED', label: 'RELATED' } },
  ],
};

export const tutorAnswer = {
  expanded_concepts: ['Stamp Act', 'Boston Tea Party'],
  sources: [
    {
      text: 'Colonial resistance grew after Parliament passed the Stamp Act in 1765.',
      module_title: 'The American Revolution',
      section: 'Colonial Resistance',
      score: 0.91,
    },
    {
      text: 'The Boston Tea Party of 1773 protested the Tea Act.',
      module_title: 'The American Revolution',
      section: 'The Road to Revolution',
      score: 0.84,
    },
  ],
  tokens: ['Taxation without representation ', 'turned colonial protest ', 'into revolution.'],
  model: 'llama3.1:8b',
  attribution: 'Content adapted from OpenStax U.S. History, licensed under CC BY 4.0.',
};

/** A server-sent-events body in the format produced by `POST /api/v1/ask/stream`. */
export function tutorStream(answer = tutorAnswer): string {
  const events = [
    {
      type: 'metadata',
      sources: answer.sources,
      expanded_concepts: answer.expanded_concepts,
      retrieved_count: answer.sources.length,
      model: answer.model,
      attribution: answer.attribution,
    },
    ...answer.tokens.map((content) => ({ type: 'token', content })),
  ];
  return [...events.map((event) => `data: ${JSON.stringify(event)}\n\n`), 'data: [DONE]\n\n'].join(
    ''
  );
}

export const quiz = {
  id: 'quiz-e2e',
  title: 'The American Revolution',
  questions: [
    {
      id: 'q1',
      text: 'Which 1765 act led colonists to protest "taxation without representation"?',
      options: [
        { id: 'a', text: 'The Stamp Act' },
        { id: 'b', text: 'The Homestead Act' },
        { id: 'c', text: 'The Judiciary Act' },
        { id: 'd', text: 'The Indian Removal Act' },
      ],
      correct_option_id: 'a',
      explanation: 'The Stamp Act of 1765 taxed printed materials in the colonies.',
      related_concept: 'Stamp Act',
      difficulty: 'easy',
    },
  ],
  student_mastery: 0.3,
  target_difficulty: 'easy',
  adapted: true,
};

export const demoStatus = {
  status: 'ready',
  positioning: 'Controlled local OpenStax client demo; not production certification infrastructure.',
  services: {
    neo4j: { status: 'ok', latency_ms: 12.3 },
    opensearch: { status: 'ok', latency_ms: 8.1 },
    ollama: { status: 'ok', latency_ms: 20.5 },
  },
  subjects: [
    {
      id: 'us_history',
      name: 'US History',
      status: 'ok',
      concept_count: 128,
      module_count: 42,
      relationship_count: 356,
    },
  ],
  latest_eval: {
    status: 'ok',
    environment_valid: true,
    generated_at: '2026-01-01T00:00:00Z',
    cases: 20,
    kg_successful_cases: 20,
    plain_successful_cases: 20,
  },
  script_readiness: {
    critical_services_ready: true,
    local_llm_ready: true,
    openstax_subject_seeded: true,
    latest_eval_valid: true,
  },
  next_actions: [],
};

const subjectFromQuery = (request: Request) =>
  new URL(request.url()).searchParams.get('subject') ?? 'us_history';

const defaultHandlers: Record<string, StubHandler> = {
  'GET /subjects': () => ({ json: subjects }),
  'GET /subjects/*/theme': (request) => {
    const subjectId = new URL(request.url()).pathname.split('/').at(-2);
    return {
      json: {
        subject_id: subjectId,
        primary_color: subjectId === 'economics' ? '#d97706' : '#dc2626',
        secondary_color: '#fca5a5',
        accent_color: '#b91c1c',
        chapter_colors: {},
      },
    };
  },
  'GET /graph/stats': (request) => ({ json: graphStats[subjectFromQuery(request)] }),
  'GET /concepts/top': () => ({ json: topConcepts }),
  'GET /graph/data': () => ({ json: graphData }),
  'POST /ask/stream': () => ({ body: tutorStream(), contentType: 'text/event-stream' }),
  'POST /ask': (request) => {
    const { question, use_kg_expansion: useKg } = request.postDataJSON();
    return {
      json: {
        question,
        answer: useKg
          ? 'With prerequisite context: colonial taxation disputes escalated into revolution.'
          : 'Colonists opposed British taxes.',
        sources: useKg ? tutorAnswer.sources : tutorAnswer.sources.slice(0, 1),
        expanded_concepts: useKg ? tutorAnswer.expanded_concepts : null,
        retrieved_count: useKg ? 8 : 5,
        model: tutorAnswer.model,
        attribution: tutorAnswer.attribution,
      },
    };
  },
  'GET /student/profile': () => ({
    json: {
      student_id: 'default',
      overall_ability: 0.3,
      mastery_levels: {},
      updated_at: '2026-01-01T00:00:00Z',
    },
  }),
  'POST /student/mastery': (request) => {
    const { concept, correct } = request.postDataJSON();
    return {
      json: {
        concept,
        previous_mastery: 0.3,
        new_mastery: correct ? 0.45 : 0.2,
        target_difficulty: correct ? 'medium' : 'easy',
        total_attempts: 1,
      },
    };
  },
  'POST /student/reset': () => ({ json: { message: 'Student profile reset' } }),
  'POST /quiz/generate-adaptive': () => ({ json: quiz }),
  'POST /quiz/generate': () => ({ json: { ...quiz, adapted: false } }),
  'POST /quiz/recommendations': () => ({
    json: {
      path_type: 'advancement',
      score_pct: 100,
      remediation: [],
      advancement: [],
      summary: 'Great work! You are ready for the next topic.',
    },
  }),
  'GET /learning-path/*': () => ({
    json: {
      target_concept: 'The American Revolution',
      prerequisites: [
        { name: 'Colonial America', depth: 1, importance: 0.7 },
        { name: 'The American Revolution', depth: 0, importance: 0.95 },
      ],
      total_concepts: 2,
    },
  }),
  'GET /demo/status': () => ({ json: demoStatus }),
};

// ---------------------------------------------------------------------------
// Routing
// ---------------------------------------------------------------------------

const API_PREFIX = '/api/v1';

const CORS_HEADERS = {
  'access-control-allow-origin': '*',
  'access-control-allow-headers': '*',
  'access-control-allow-methods': 'GET, POST, OPTIONS',
};

/** "GET /subjects/*\/theme" -> matcher on method + path (relative to /api/v1). */
function compileRoute(route: string) {
  const [method, path] = route.split(' ');
  const pattern = new RegExp(
    `^${path.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '[^/]+')}$`
  );
  return (request: Request) =>
    request.method() === method &&
    pattern.test(new URL(request.url()).pathname.slice(API_PREFIX.length));
}

export class ApiMock {
  private readonly handlers: Array<{ route: string; matches: (r: Request) => boolean; handler: StubHandler }> = [];
  private readonly requests: Request[] = [];
  readonly unhandled: string[] = [];

  constructor() {
    for (const [route, handler] of Object.entries(defaultHandlers)) {
      this.on(route, handler);
    }
  }

  /** Answer "<METHOD> <path>" (path relative to /api/v1, `*` = one segment) with `response`. */
  on(route: string, response: StubHandler | StubResponse): void {
    const handler = typeof response === 'function' ? response : () => response;
    // Newest registration wins, so tests can override the defaults.
    this.handlers.unshift({ route, matches: compileRoute(route), handler });
  }

  /** Requests the page sent to "<METHOD> <path>". */
  calls(route: string): Request[] {
    const matches = compileRoute(route);
    return this.requests.filter(matches);
  }

  async handle(route: Route): Promise<void> {
    const request = route.request();
    if (request.method() === 'OPTIONS') {
      await route.fulfill({ status: 204, headers: CORS_HEADERS });
      return;
    }
    this.requests.push(request);
    const entry = this.handlers.find(({ matches }) => matches(request));
    if (!entry) {
      const { pathname } = new URL(request.url());
      this.unhandled.push(`${request.method()} ${pathname}`);
      await route.fulfill({
        status: 404,
        headers: CORS_HEADERS,
        json: { detail: 'No e2e stub for this endpoint' },
      });
      return;
    }
    const { status = 200, json, body, contentType } = await entry.handler(request);
    await route.fulfill({
      status,
      headers: CORS_HEADERS,
      ...(json !== undefined ? { json } : { body: body ?? '', contentType }),
    });
  }
}

async function installApiMock(page: Page): Promise<ApiMock> {
  const api = new ApiMock();
  await page.route(
    (url) => url.pathname.startsWith(`${API_PREFIX}/`),
    (route) => api.handle(route)
  );
  return api;
}

export const test = base.extend<{ api: ApiMock }>({
  api: [
    async ({ page }, provide) => {
      const pageErrors: Error[] = [];
      page.on('pageerror', (error) => pageErrors.push(error));

      const api = await installApiMock(page);
      await provide(api);

      expect(api.unhandled, 'requests without an e2e stub').toEqual([]);
      expect(pageErrors, 'uncaught errors in the page').toEqual([]);
    },
    { auto: true },
  ],
});
