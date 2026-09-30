/**
 * Fake Cytoscape for unit tests: `jest.mock('cytoscape', () =>
 * require('./helpers/cytoscapeMock').createCytoscapeMock())`.
 *
 * Every cytoscape() call creates a new fake instance (listed in `cytoscape.instances`), so tests
 * can tell whether a graph was rebuilt. Node collections filter the real node data, and event
 * handlers registered with `on()` are kept in `instance.handlers` ("tap node", "tap", ...).
 */

type Item = Record<string, unknown>;

export interface FakeCollection {
  length: number;
  removeClass: jest.Mock;
  addClass: jest.Mock;
  not: jest.Mock;
  edgesWith: jest.Mock;
  filter: jest.Mock;
}

export interface FakeCy {
  options: { elements: { nodes: Array<{ data: Item }>; edges: Array<{ data: Item }> }; style: Array<{ selector: string; style: Record<string, unknown> }> };
  handlers: Record<string, (event: unknown) => void>;
  styleUpdate: jest.Mock;
  nodes: jest.Mock;
  edges: jest.Mock;
  zoom: jest.Mock;
  center: jest.Mock;
  fit: jest.Mock;
  destroy: jest.Mock;
  style: jest.Mock;
  on: jest.Mock;
}

function collection(items: Item[]): FakeCollection {
  const result: FakeCollection = {
    length: items.length,
    removeClass: jest.fn(() => result),
    addClass: jest.fn(() => result),
    not: jest.fn(() => result),
    edgesWith: jest.fn(() => collection([])),
    filter: jest.fn((predicate: (node: { data: (key: string) => unknown }) => boolean) =>
      collection(items.filter((item) => predicate({ data: (key: string) => item[key] })))
    ),
  };
  return result;
}

export function createCytoscapeMock() {
  const instances: FakeCy[] = [];
  const cytoscape = jest.fn((options: FakeCy['options']) => {
    const nodes = collection(options.elements.nodes.map((node) => node.data));
    const edges = collection(options.elements.edges.map((edge) => edge.data));
    const handlers: FakeCy['handlers'] = {};
    const styleUpdate = jest.fn();
    const instance: FakeCy = {
      options,
      handlers,
      styleUpdate,
      nodes: jest.fn(() => nodes),
      edges: jest.fn(() => edges),
      zoom: jest.fn().mockReturnValue(1),
      center: jest.fn(),
      fit: jest.fn(),
      destroy: jest.fn(),
      style: jest.fn(() => ({ update: styleUpdate })),
      on: jest.fn((event: string, selectorOrHandler: unknown, handler?: unknown) => {
        const key = typeof selectorOrHandler === 'string' ? `${event} ${selectorOrHandler}` : event;
        handlers[key] = (handler ?? selectorOrHandler) as (event: unknown) => void;
      }),
    };
    instances.push(instance);
    return instance;
  });
  return Object.assign(cytoscape, { use: jest.fn(), instances });
}

export type CytoscapeMock = ReturnType<typeof createCytoscapeMock>;

/** A node as passed to a "tap node" handler. */
export function fakeNode(id: string, label: string, importance: number, connections = 2) {
  return {
    id: () => id,
    data: (key: string) => ({ label, importance })[key as 'label' | 'importance'],
    addClass: jest.fn(),
    neighborhood: () => ({
      nodes: () => ({ length: connections, addClass: jest.fn() }),
      edges: () => ({ addClass: jest.fn() }),
    }),
  };
}
