# Adaptive Knowledge Graph - Frontend

Modern, responsive web interface for the Adaptive Knowledge Graph project, built with Next.js 14, TypeScript, and Tailwind CSS.

## Features

- **Interactive Knowledge Graph Visualization** - Explore Biology concepts with Cytoscape.js
- **AI Tutor Chat** - Ask questions with KG-aware RAG
- **Comparison View** - See KG-RAG vs Regular RAG side-by-side
- **Comprehensive Testing** - Unit tests (Jest) + E2E tests (Playwright)
- **Backend API Integration** - Designed to run against the FastAPI service
- **Fully Responsive** - Mobile, tablet, and desktop optimized

---

## Quick Start

### Prerequisites

- Node.js 18+ and npm
- Backend API running on `http://localhost:8000`

### Installation

```bash
# Install dependencies
npm install

# Copy environment file
cp .env.example .env.local

# Start development server
npm run dev
```

Visit `http://localhost:3000`

---

## Available Scripts

### Development
```bash
npm run dev          # Start dev server (http://localhost:3000)
npm run build        # Build for production
npm run start        # Start production server
npm run lint         # Run ESLint
npm run type-check   # Run TypeScript type checking
```

### Testing
```bash
npm test                    # Run Jest unit tests
npm run test:watch          # Run tests in watch mode
npm run test:coverage       # Run tests with coverage report
npm run test:e2e            # Run Playwright E2E tests
npm run test:e2e:ui         # Run E2E tests with UI
```

---

## Project Structure

```
frontend/
├── app/                    # Next.js 14 App Router pages
│   ├── page.tsx           # Home page (/)
│   ├── graph/             # Graph visualization (/graph)
│   ├── chat/              # AI chat interface (/chat)
│   ├── comparison/        # KG-RAG comparison (/comparison)
│   ├── about/             # About page (/about)
│   ├── layout.tsx         # Root layout
│   └── globals.css        # Global styles
├── components/            # Reusable React components
│   └── KnowledgeGraph.tsx # Cytoscape graph component
├── lib/                   # Utilities and services
│   ├── api-client.ts      # API client with types
│   └── types.ts           # TypeScript type definitions
├── tests/
│   ├── unit/              # Jest unit tests
│   └── e2e/               # Playwright E2E tests
├── public/                # Static assets
├── package.json
├── tsconfig.json
├── tailwind.config.ts
├── jest.config.js
├── playwright.config.ts
└── README.md
```

---

## Environment Variables

Create `.env.local` from `.env.example`:

```env
# Backend API URL
NEXT_PUBLIC_API_URL=http://localhost:8000

```

---

## Key Features

### 1. Knowledge Graph Visualization (`/graph`)

Interactive graph powered by Cytoscape.js:
- **Node sizing** by concept importance (PageRank scores)
- **Edge coloring** by relationship type (PREREQ=red, COVERS=blue, RELATED=purple)
- **Click interactions** to select nodes and highlight neighbors
- **Zoom & pan** controls
- **Legend** and instructions sidebar

### 2. AI Tutor Chat (`/chat`)

Conversational interface with:
- **KG expansion toggle** - Show difference between KG-aware and regular RAG
- **Real-time streaming** (if supported by backend)
- **Expanded concepts display** - See which concepts were pulled in
- **Source citations** - View textbook sources with scores
- **Example questions** - Quick start prompts

### 3. Comparison View (`/comparison`)

Side-by-side comparison:
- **With KG Expansion** (left panel)
- **Regular RAG** (right panel)
- Shows concept count, answer quality difference
- Clear visual distinction (green vs gray theme)

### 4. Responsive Design

- Mobile-first approach
- Tailwind CSS for consistent styling
- Breakpoints: `sm:640px`, `md:768px`, `lg:1024px`, `xl:1280px`

---

## Testing

### Unit Tests (Jest + React Testing Library)

Test individual components and utilities:

```bash
npm test                 # Run all tests
npm run test:watch       # Watch mode for TDD
npm run test:coverage    # Generate coverage report
```

**Coverage targets:**
- Branches: 70%
- Functions: 70%
- Lines: 70%
- Statements: 70%

### E2E Tests (Playwright)

Test full user flows across browsers:

```bash
npm run test:e2e         # Run E2E tests (headless)
npm run test:e2e:ui      # Run with UI for debugging
```

**Test coverage:**
- Home page navigation
- Graph interaction (click, zoom, select)
- Chat message flow
- Comparison feature
- Responsive layouts

### Manual Testing

See `TESTING_CHECKLIST.md` for comprehensive manual test scenarios.

---

## API Integration

### API Client (`lib/api-client.ts`)

Typed API methods:
```typescript
import { apiClient } from '@/lib/api-client';

// Get graph statistics
const stats = await apiClient.getGraphStats();

// Ask a question
const response = await apiClient.askQuestion({
  question: 'What is photosynthesis?',
  use_kg_expansion: true,
  top_k: 5,
});

// Get graph data for visualization
const graphData = await apiClient.getGraphData();
```

### Backend Requirement

The frontend expects the FastAPI backend to be available. It does not currently
implement automatic mock-data fallback; keep tests and demos wired to explicit
mocks or a running backend.

---

## Deployment

### Production Build

```bash
npm run build
npm start
```

### Docker

```dockerfile
FROM node:20-alpine

WORKDIR /app
COPY package*.json ./
RUN npm ci --production
COPY . .
RUN npm run build

EXPOSE 3000
CMD ["npm", "start"]
```

### Environment Variables (Production)

```env
NEXT_PUBLIC_API_URL=https://api.yourdomain.com
```

---

## Troubleshooting

### "API client error: Unable to reach the server"

**Cause:** Backend is not running or incorrect URL

**Fix:**
1. Check backend is running: `curl http://localhost:8000/health`
2. Verify `NEXT_PUBLIC_API_URL` in `.env.local`
3. Restart the frontend after changing environment variables

### Graph visualization not rendering

**Cause:** Cytoscape SSR issue

**Fix:** Component uses `dynamic import` with `ssr: false`. Check browser console for errors.

### Tests failing

**Cause:** Missing dependencies or configuration

**Fix:**
```bash
# Reinstall dependencies
rm -rf node_modules package-lock.json
npm install

# Install Playwright browsers
npx playwright install
```

---

## Contributing

1. Follow TypeScript strict mode
2. Write tests for new features
3. Run linter before committing: `npm run lint`
4. Ensure tests pass: `npm test && npm run test:e2e`
5. Check type safety: `npm run type-check`

---

## License

MIT License - See LICENSE file for details.

---

## Credits

- **Content:** OpenStax Biology 2e (CC BY 4.0)
- **Graph Viz:** Cytoscape.js
- **Icons:** Lucide React
- **Framework:** Next.js 14

---

## Support

- **Documentation:** See `TESTING_CHECKLIST.md`
- **Issues:** Report bugs with screenshots and browser info
- **Questions:** Include steps to reproduce

---

**Built for the BLIS Department VP Demo** 🚀
