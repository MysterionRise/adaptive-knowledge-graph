import type { FullConfig } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const API_URL = process.env.API_URL || 'http://localhost:8000';
const FRONTEND_URL = process.env.FRONTEND_URL || 'http://localhost:3000';

/** File used to pass Ollama status from globalSetup to test workers. */
const STATUS_FILE = path.join(__dirname, '.ollama-status');

function isIntegrationTargeted(): boolean {
  // If --project is specified and doesn't include 'integration', skip setup.
  const args = process.argv.join(' ');
  const projectMatch = args.match(/--project[=\s]+(\S+)/);
  if (projectMatch && !projectMatch[1].includes('integration')) {
    return false;
  }
  // If no --project flag, all projects run — integration is included.
  return true;
}

async function globalSetup(_config: FullConfig) {
  // Skip setup entirely when not running integration tests
  if (!isIntegrationTargeted()) {
    return;
  }

  console.log('\n=== Integration Test Global Setup ===\n');

  // 1. Check backend health
  console.log(`Checking backend at ${API_URL}/health/ready ...`);
  let healthData: any;
  try {
    const res = await fetch(`${API_URL}/health/ready`);
    if (!res.ok) {
      throw new Error(`Backend returned ${res.status}`);
    }
    healthData = await res.json();
    console.log(`  Backend status: ${healthData.status}`);
  } catch (e: any) {
    throw new Error(
      `Backend is not running at ${API_URL}.\n` +
        `  Start it with: make run-api\n` +
        `  Error: ${e.message}`
    );
  }

  // 2. Check Neo4j has seed data
  console.log('Checking Neo4j seed data via /api/v1/graph/stats ...');
  try {
    const res = await fetch(`${API_URL}/api/v1/graph/stats?subject=us_history`);
    if (!res.ok) {
      throw new Error(`Graph stats returned ${res.status}`);
    }
    const stats = await res.json();
    if (!stats.concept_count || stats.concept_count === 0) {
      throw new Error(
        'Neo4j has 0 concepts. Seed data is required.\n' +
          '  Run: poetry run python scripts/ingest_books.py\n' +
          '       make build-kg SUBJECT=us_history\n' +
          '       make index-rag SUBJECT=us_history'
      );
    }
    console.log(
      `  Neo4j: ${stats.concept_count} concepts, ${stats.module_count} modules, ${stats.relationship_count} relationships`
    );
  } catch (e: any) {
    if (e.message.includes('Neo4j has 0 concepts')) throw e;
    throw new Error(
      `Cannot verify Neo4j seed data.\n  Error: ${e.message}\n` +
        `  Ensure Neo4j is running: docker compose -f infra/compose/compose.yaml up -d neo4j`
    );
  }

  // 3. Check available subjects
  console.log('Checking available subjects ...');
  try {
    const res = await fetch(`${API_URL}/api/v1/subjects`);
    if (res.ok) {
      const data = await res.json();
      const subjectNames = data.subjects?.map((s: any) => s.id).join(', ') || 'none';
      console.log(`  Subjects: ${subjectNames}`);
    }
  } catch {
    console.log('  Warning: Could not fetch subjects list');
  }

  // 4. Check Ollama availability
  console.log('Checking Ollama availability ...');
  let ollamaAvailable = false;
  try {
    if (healthData?.services?.ollama?.status === 'ok') {
      ollamaAvailable = true;
    }
  } catch {
    // Ollama not available
  }

  // Write status to file so test workers can read it (env vars don't propagate
  // from globalSetup to test workers since they run in separate processes).
  fs.writeFileSync(STATUS_FILE, JSON.stringify({ ollamaAvailable }));

  console.log(
    `  Ollama: ${ollamaAvailable ? 'AVAILABLE - all tests will run' : 'NOT AVAILABLE - LLM tests will be skipped'}`
  );

  // 5. Reset student profile for clean state
  console.log('Resetting student profile ...');
  try {
    const res = await fetch(`${API_URL}/api/v1/student/reset`, {
      method: 'POST',
    });
    if (res.ok) {
      console.log('  Student profile reset');
    } else {
      console.log(`  Warning: Student reset returned ${res.status}`);
    }
  } catch {
    console.log('  Warning: Could not reset student profile');
  }

  // 6. Check frontend
  console.log(`Checking frontend at ${FRONTEND_URL} ...`);
  try {
    const res = await fetch(FRONTEND_URL);
    if (!res.ok) {
      throw new Error(`Frontend returned ${res.status}`);
    }
    console.log('  Frontend is running');
  } catch (e: any) {
    throw new Error(
      `Frontend is not running at ${FRONTEND_URL}.\n` +
        `  Start it with: cd frontend && npm run dev\n` +
        `  Error: ${e.message}`
    );
  }

  console.log('\n=== Global Setup Complete ===\n');
}

export default globalSetup;
