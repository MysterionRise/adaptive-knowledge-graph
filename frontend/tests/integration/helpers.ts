import * as fs from 'fs';
import * as path from 'path';

/** Backend API URL. */
export const API_URL = process.env.API_URL || 'http://localhost:8000';

/** Timeout for operations that depend on the LLM (streaming answers, quiz generation). */
export const LLM_TIMEOUT = 120_000;

/** Timeout for operations that depend on data fetching (graph, stats). */
export const DATA_TIMEOUT = 30_000;

/** File written by global-setup.ts to pass Ollama status to test workers. */
const STATUS_FILE = path.join(__dirname, '.ollama-status');

/**
 * Check if Ollama is available.
 *
 * Reads from the status file written by global-setup.ts (which runs in a
 * separate process from test workers). Falls back to a live health check
 * if the file doesn't exist.
 */
export async function isOllamaAvailable(): Promise<boolean> {
  // Try reading status file first (set by globalSetup)
  try {
    const data = JSON.parse(fs.readFileSync(STATUS_FILE, 'utf-8'));
    return data.ollamaAvailable === true;
  } catch {
    // File doesn't exist — fall through to live check
  }

  // Fallback: probe the health endpoint at runtime
  try {
    const res = await fetch(`${API_URL}/health/ready`);
    if (!res.ok) return false;
    const data = await res.json();
    return data?.services?.ollama?.status === 'ok';
  } catch {
    return false;
  }
}
