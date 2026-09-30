// Learn more: https://github.com/testing-library/jest-dom
import '@testing-library/jest-dom'

// Mock next/navigation
jest.mock('next/navigation', () => ({
  useRouter() {
    return {
      push: jest.fn(),
      replace: jest.fn(),
      prefetch: jest.fn(),
      back: jest.fn(),
    }
  },
  usePathname() {
    return ''
  },
  useSearchParams() {
    return new URLSearchParams()
  },
}))

// Mock window.matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: jest.fn().mockImplementation(query => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: jest.fn(),
    removeListener: jest.fn(),
    addEventListener: jest.fn(),
    removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  })),
})

// Mock ResizeObserver
class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}
window.ResizeObserver = ResizeObserverMock

// Mock IntersectionObserver
class IntersectionObserverMock {
  constructor() {}
  observe() {}
  unobserve() {}
  disconnect() {}
}
window.IntersectionObserver = IntersectionObserverMock

// Unit tests run without a backend. axios uses jsdom's XMLHttpRequest, which would open a real
// socket and keep Jest alive until the request times out, so fail fast with a clear error instead.
const originalXhrOpen = window.XMLHttpRequest.prototype.open
window.XMLHttpRequest.prototype.open = function open(method, url, ...rest) {
  this.unitTestRequest = `${method} ${url}`
  return originalXhrOpen.call(this, method, url, ...rest)
}
window.XMLHttpRequest.prototype.send = function send() {
  throw new Error(
    `Unexpected network request in a unit test (${this.unitTestRequest}). ` +
      'Mock @/lib/api-client, the component that calls it, or global.fetch.'
  )
}

// Suppress console errors during tests for expected errors
const originalError = console.error
beforeAll(() => {
  console.error = (...args) => {
    // Suppress specific expected errors
    if (
      typeof args[0] === 'string' &&
      (args[0].includes('ErrorBoundary caught an error') ||
       args[0].includes('Warning: ReactDOM.render is no longer supported'))
    ) {
      return
    }
    originalError.call(console, ...args)
  }
})

afterAll(() => {
  console.error = originalError
})
