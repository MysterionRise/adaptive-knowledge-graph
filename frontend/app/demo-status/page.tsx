'use client';

import {
  AlertTriangle,
  CheckCircle2,
  Database,
  FileCheck2,
  Gauge,
  Loader2,
  RefreshCw,
  Server,
  XCircle,
} from 'lucide-react';
import { apiClient } from '@/lib/api-client';
import { describeError } from '@/lib/api-errors';
import type { DemoReadinessStatus, DemoStatusResponse } from '@/lib/types';
import { useApiQuery } from '@/lib/useApiQuery';
import ErrorMessage from '@/components/ErrorMessage';

const statusLabels: Record<DemoReadinessStatus, string> = {
  ok: 'Ready',
  degraded: 'Needs attention',
  error: 'Blocked',
  missing: 'Missing',
};

const statusClasses: Record<DemoReadinessStatus, string> = {
  ok: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  degraded: 'bg-amber-50 text-amber-700 border-amber-200',
  error: 'bg-red-50 text-red-700 border-red-200',
  missing: 'bg-gray-50 text-gray-700 border-gray-200',
};

function StatusIcon({ status }: { status: DemoReadinessStatus }) {
  if (status === 'ok') return <CheckCircle2 className="h-5 w-5" aria-hidden="true" />;
  if (status === 'degraded') return <AlertTriangle className="h-5 w-5" aria-hidden="true" />;
  return <XCircle className="h-5 w-5" aria-hidden="true" />;
}

function StatusBadge({ status }: { status: DemoReadinessStatus }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-semibold ${statusClasses[status]}`}
    >
      <StatusIcon status={status} />
      {statusLabels[status]}
    </span>
  );
}

function OverallBadge({ status }: { status: DemoStatusResponse['status'] }) {
  const label = status === 'ready' ? 'Demo ready' : status === 'degraded' ? 'Rehearsal required' : 'Not ready';
  const className =
    status === 'ready'
      ? 'bg-emerald-600 text-white'
      : status === 'degraded'
        ? 'bg-amber-500 text-white'
        : 'bg-red-600 text-white';
  return <span className={`rounded-md px-3 py-1.5 text-sm font-semibold ${className}`}>{label}</span>;
}

export default function DemoStatusPage() {
  const demoStatus = useApiQuery('demo-status', (signal) => apiClient.getDemoStatus({ signal }));
  const { isLoading, error } = demoStatus;
  // The previous report stays visible while it is being refreshed
  const status = error ? undefined : demoStatus.data;

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-4 py-5 sm:px-6 lg:px-8">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Demo Status</h1>
            <p className="text-sm text-gray-600">
              Checks that the local services, the seeded subject data and the latest evaluation
              are ready.
            </p>
          </div>
          <button
            type="button"
            onClick={demoStatus.retry}
            disabled={isLoading}
            className="inline-flex items-center gap-2 rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isLoading ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <RefreshCw className="h-4 w-4" aria-hidden="true" />
            )}
            Refresh
          </button>
        </div>
      </header>

      <main id="main-content" className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        {isLoading && !status ? (
          <div className="flex min-h-[360px] items-center justify-center" role="status">
            <div className="flex items-center gap-3 text-gray-600">
              <Loader2 className="h-6 w-6 animate-spin" aria-hidden="true" />
              Loading demo readiness...
            </div>
          </div>
        ) : error ? (
          <ErrorMessage
            title="Unable to load demo readiness."
            message={describeError(error)}
            onRetry={demoStatus.retry}
          />
        ) : status ? (
          <div className="space-y-8">
            <section className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <div className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-gray-500">
                    <Gauge className="h-4 w-4" />
                    Demo Readiness
                  </div>
                  <h2 className="text-xl font-bold text-gray-900">{status.positioning}</h2>
                </div>
                <OverallBadge status={status.status} />
              </div>
            </section>

            <section className="grid gap-4 md:grid-cols-3">
              {Object.entries(status.services).map(([name, service]) => (
                <div key={name} className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
                  <div className="mb-4 flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <Server className="h-5 w-5 text-gray-500" />
                      <h3 className="font-semibold capitalize text-gray-900">{name}</h3>
                    </div>
                    <StatusBadge status={service.status} />
                  </div>
                  <p className="min-h-[44px] text-sm text-gray-600">
                    {service.message || 'Service is available for the local demo.'}
                  </p>
                  {service.latency_ms != null && (
                    <p className="mt-3 text-xs font-medium text-gray-500">
                      Latency: {service.latency_ms.toFixed(1)}ms
                    </p>
                  )}
                </div>
              ))}
            </section>

            <section className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
              <div className="mb-5 flex items-center gap-2">
                <Database className="h-5 w-5 text-gray-500" />
                <h2 className="text-lg font-bold text-gray-900">OpenStax Subject Data</h2>
              </div>
              <div className="overflow-hidden rounded-md border border-gray-200">
                <table className="min-w-full divide-y divide-gray-200 text-sm">
                  <thead className="bg-gray-50 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">
                    <tr>
                      <th className="px-4 py-3">Subject</th>
                      <th className="px-4 py-3">Status</th>
                      <th className="px-4 py-3">Concepts</th>
                      <th className="px-4 py-3">Modules</th>
                      <th className="px-4 py-3">Relationships</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200 bg-white">
                    {status.subjects.map((subject) => (
                      <tr key={subject.id}>
                        <td className="px-4 py-3 font-medium text-gray-900">{subject.name}</td>
                        <td className="px-4 py-3">
                          <StatusBadge status={subject.status} />
                        </td>
                        <td className="px-4 py-3 text-gray-700">{subject.concept_count.toLocaleString()}</td>
                        <td className="px-4 py-3 text-gray-700">{subject.module_count.toLocaleString()}</td>
                        <td className="px-4 py-3 text-gray-700">{subject.relationship_count.toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="grid gap-4 lg:grid-cols-[1fr_1fr]">
              <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
                <div className="mb-4 flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <FileCheck2 className="h-5 w-5 text-gray-500" />
                    <h2 className="text-lg font-bold text-gray-900">Latest Evaluation</h2>
                  </div>
                  <StatusBadge status={status.latest_eval.status} />
                </div>
                <dl className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <dt className="text-gray-500">Cases</dt>
                    <dd className="font-semibold text-gray-900">{status.latest_eval.cases}</dd>
                  </div>
                  <div>
                    <dt className="text-gray-500">Environment valid</dt>
                    <dd className="font-semibold text-gray-900">
                      {status.latest_eval.environment_valid ? 'Yes' : 'No'}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-gray-500">KG successful</dt>
                    <dd className="font-semibold text-gray-900">{status.latest_eval.kg_successful_cases}</dd>
                  </div>
                  <div>
                    <dt className="text-gray-500">Plain successful</dt>
                    <dd className="font-semibold text-gray-900">{status.latest_eval.plain_successful_cases}</dd>
                  </div>
                </dl>
                {status.latest_eval.message && (
                  <p className="mt-4 rounded-md bg-amber-50 p-3 text-sm text-amber-800">
                    {status.latest_eval.message}
                  </p>
                )}
              </div>

              <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
                <h2 className="mb-4 text-lg font-bold text-gray-900">Next Actions</h2>
                {status.next_actions.length > 0 ? (
                  <ul className="space-y-3 text-sm text-gray-700">
                    {status.next_actions.map((action) => (
                      <li key={action} className="flex gap-2">
                        <AlertTriangle className="mt-0.5 h-4 w-4 flex-none text-amber-500" />
                        <span>{action}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-gray-700">
                    The local stack, seeded OpenStax data, local LLM, and latest eval are ready for rehearsal.
                  </p>
                )}
              </div>
            </section>
          </div>
        ) : null}
      </main>
    </div>
  );
}
