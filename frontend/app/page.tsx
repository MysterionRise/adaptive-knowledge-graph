'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { apiClient } from '@/lib/api-client';
import { describeError } from '@/lib/api-errors';
import { useAppStore } from '@/lib/store';
import { isSubjectAvailable } from '@/lib/subjects';
import { useApiQuery } from '@/lib/useApiQuery';
import { StatsSkeleton } from '@/components/Skeleton';
import ErrorMessage from '@/components/ErrorMessage';
import {
  Network,
  MessageSquare,
  TrendingUp,
  Zap,
  GraduationCap,
  Trophy,
  Target,
  BookOpen,
  ArrowRight,
  Sparkles,
} from 'lucide-react';
import SubjectPicker from '@/components/SubjectPicker';

const TOP_CONCEPT_COUNT = 6;

const chatHref = (concept: string) =>
  `/chat?question=${encodeURIComponent(`Explain ${concept}`)}`;

export default function Home() {
  const router = useRouter();
  const currentSubject = useAppStore((state) => state.currentSubject);
  const masteryMap = useAppStore((state) => state.masteryMap);

  const stats = useApiQuery(`stats:${currentSubject}`, (signal) =>
    apiClient.getGraphStats(currentSubject, { signal })
  );
  const topConcepts = useApiQuery(`top-concepts:${currentSubject}`, (signal) =>
    apiClient.getTopConceptsForSubject(TOP_CONCEPT_COUNT, currentSubject, { signal })
  );
  // Only for the attribution footer; SubjectPicker shows its own errors.
  const subjects = useApiQuery('subjects', (signal) => apiClient.getSubjects({ signal }));
  const availableSubjectNames = (subjects.data?.subjects ?? [])
    .filter(isSubjectAvailable)
    .map((subject) => subject.name);

  // Calculate overall progress from mastery map
  const masteryEntries = Object.values(masteryMap);
  const masteredCount = masteryEntries.filter(m => m.masteryLevel >= 0.7).length;
  const inProgressCount = masteryEntries.filter(m => m.masteryLevel >= 0.3 && m.masteryLevel < 0.7).length;
  const totalTracked = masteryEntries.length;
  const overallMastery = totalTracked > 0
    ? masteryEntries.reduce((sum, m) => sum + m.masteryLevel, 0) / totalTracked
    : 0;

  const topConceptNames = (topConcepts.data ?? []).map((concept) => concept.name);

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-purple-50">
      {/* Header */}
      <header className="bg-white shadow-sm border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h1 className="text-3xl font-bold text-gray-900">
                Adaptive Knowledge Graph
              </h1>
              <p className="mt-2 text-gray-600">
                Grounded AI tutoring over open textbooks
              </p>
            </div>
            <SubjectPicker />
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main id="main-content" className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        {/* Hero Section */}
        <div className="text-center mb-16">
          <h2 className="text-4xl font-extrabold text-gray-900 sm:text-5xl sm:tracking-tight lg:text-6xl">
            Adaptive Learning Over
            <span className="text-primary-600"> Open Textbooks</span>
          </h2>
          <p className="mt-6 max-w-2xl mx-auto text-xl text-gray-500">
            An open-source demo that combines a knowledge graph with retrieval-augmented
            generation over OpenStax textbooks: grounded answers with citations, adaptive
            practice, and measurable answer quality.
          </p>
          <div className="mt-8 flex flex-wrap justify-center gap-4">
            <Link
              href="/graph"
              className="inline-flex items-center px-5 py-2.5 border border-transparent text-sm font-medium rounded-md text-white bg-primary-600 hover:bg-primary-700 transition-colors"
            >
              Explore Graph
            </Link>
            <Link
              href="/chat"
              className="inline-flex items-center px-5 py-2.5 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 transition-colors"
            >
              Ask Questions
            </Link>
          </div>
        </div>

        {/* Statistics Dashboard */}
        <section className="mb-16" aria-labelledby="stats-heading">
          <h3 id="stats-heading" className="text-2xl font-bold text-gray-900 mb-6 text-center">
            Knowledge Graph Statistics
          </h3>
          {stats.isLoading ? (
            <StatsSkeleton />
          ) : stats.error || !stats.data ? (
            <ErrorMessage
              title="Unable to load statistics."
              message={describeError(stats.error)}
              onRetry={stats.retry}
            />
          ) : (
            <div className="grid grid-cols-1 gap-6 sm:grid-cols-3">
              <StatCard
                title="Concepts"
                value={stats.data.concept_count}
                icon={<Network className="w-8 h-8" />}
                color="blue"
                description="Concepts in the knowledge graph"
              />
              <StatCard
                title="Study Modules"
                value={stats.data.module_count}
                icon={<TrendingUp className="w-8 h-8" />}
                color="purple"
                description="Textbook chapters available"
              />
              <StatCard
                title="Connections"
                value={stats.data.relationship_count}
                icon={<Zap className="w-8 h-8" />}
                color="green"
                description="Causal links & prerequisites"
              />
            </div>
          )}
        </section>

        {/* Learning Progress Section */}
        <div className="mb-16">
          <div className="flex items-center justify-center gap-3 mb-6">
            <Trophy className="w-7 h-7 text-amber-500" aria-hidden="true" />
            <h3 className="text-2xl font-bold text-gray-900">
              Your Learning Progress
            </h3>
          </div>

          <div className="bg-white rounded-xl shadow-lg p-6 border border-gray-200">
            {totalTracked > 0 ? (
              <div className="space-y-6">
                {/* Overall Progress */}
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-gray-600 mb-1">Overall Mastery</p>
                    <p className="text-3xl font-bold text-gray-900">
                      {Math.round(overallMastery * 100)}%
                    </p>
                  </div>
                  <div className="flex gap-6 text-center">
                    <div>
                      <p className="text-2xl font-bold text-emerald-600">{masteredCount}</p>
                      <p className="text-xs text-gray-500">Mastered</p>
                    </div>
                    <div>
                      <p className="text-2xl font-bold text-blue-600">{inProgressCount}</p>
                      <p className="text-xs text-gray-500">In Progress</p>
                    </div>
                    <div>
                      <p className="text-2xl font-bold text-gray-400">{totalTracked}</p>
                      <p className="text-xs text-gray-500">Total Tracked</p>
                    </div>
                  </div>
                </div>

                {/* Progress Bar */}
                <div className="h-4 bg-gray-100 rounded-full overflow-hidden" aria-hidden="true">
                  <div
                    className="h-full bg-gradient-to-r from-blue-500 to-emerald-500 transition-all duration-500"
                    style={{ width: `${overallMastery * 100}%` }}
                  />
                </div>

                {/* Concept Progress List */}
                <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                  {Object.entries(masteryMap).slice(0, 6).map(([name, data]) => (
                    <Link
                      key={name}
                      href={chatHref(name)}
                      className="block p-3 bg-gray-50 rounded-lg border border-gray-200 hover:border-blue-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 transition-all"
                    >
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-sm font-medium text-gray-900 truncate">{name}</span>
                        <span className={`text-xs font-semibold ${
                          data.masteryLevel >= 0.7 ? 'text-emerald-600' :
                          data.masteryLevel >= 0.4 ? 'text-blue-600' : 'text-gray-400'
                        }`}>
                          {Math.round(data.masteryLevel * 100)}%
                        </span>
                      </div>
                      <div className="h-1.5 bg-gray-200 rounded-full overflow-hidden" aria-hidden="true">
                        <div
                          className={`h-full transition-all ${
                            data.masteryLevel >= 0.7 ? 'bg-emerald-500' :
                            data.masteryLevel >= 0.4 ? 'bg-blue-500' : 'bg-gray-300'
                          }`}
                          style={{ width: `${data.masteryLevel * 100}%` }}
                        />
                      </div>
                    </Link>
                  ))}
                </div>
              </div>
            ) : (
              <div className="text-center py-8">
                <Sparkles className="w-12 h-12 text-amber-400 mx-auto mb-4" aria-hidden="true" />
                <h4 className="text-lg font-semibold text-gray-900 mb-2">
                  Start Your Learning Journey
                </h4>
                <p className="text-gray-600 mb-6 max-w-md mx-auto">
                  Take assessments and ask questions to track your progress across key concepts.
                </p>
                <div className="flex justify-center gap-4">
                  <Link
                    href="/assessment"
                    className="inline-flex items-center gap-2 px-5 py-2.5 bg-amber-500 text-white rounded-lg font-medium hover:bg-amber-600 transition-colors"
                  >
                    <BookOpen className="w-4 h-4" aria-hidden="true" />
                    Take Assessment
                  </Link>
                  <Link
                    href="/chat"
                    className="inline-flex items-center gap-2 px-5 py-2.5 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 transition-colors"
                  >
                    <MessageSquare className="w-4 h-4" aria-hidden="true" />
                    Ask AI Tutor
                  </Link>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Quick Start Concepts */}
        {(topConcepts.error || topConceptNames.length > 0) && !topConcepts.isLoading && (
          <section className="mb-16" aria-labelledby="start-learning-heading">
            <div className="flex items-center justify-center gap-3 mb-6">
              <Target className="w-6 h-6 text-blue-600" aria-hidden="true" />
              <h3 id="start-learning-heading" className="text-2xl font-bold text-gray-900">
                Start Learning
              </h3>
            </div>

            {topConcepts.error ? (
              <ErrorMessage
                title="Unable to load suggested concepts."
                message={describeError(topConcepts.error)}
                onRetry={topConcepts.retry}
              />
            ) : (
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
                {topConceptNames.map((concept) => (
                  <button
                    key={concept}
                    type="button"
                    onClick={() => router.push(chatHref(concept))}
                    className="group p-4 bg-white rounded-lg border border-gray-200 hover:border-blue-400 hover:shadow-md transition-all text-left"
                  >
                    <p className="font-medium text-gray-900 group-hover:text-blue-600 transition-colors text-sm">
                      {concept}
                    </p>
                    <div className="flex items-center gap-1 mt-2 text-xs text-gray-500 group-hover:text-blue-500">
                      <span>Learn</span>
                      <ArrowRight className="w-3 h-3" aria-hidden="true" />
                    </div>
                  </button>
                ))}
              </div>
            )}
          </section>
        )}

        {/* Feature Cards */}
        <div className="mb-16">
          <h3 className="text-2xl font-bold text-gray-900 mb-6 text-center">
            Key Features
          </h3>
          <div className="grid grid-cols-1 gap-8 md:grid-cols-2 lg:grid-cols-4">
            <FeatureCard
              title="Knowledge Map"
              description="Visualize concepts and their prerequisite relationships"
              icon={<Network className="w-6 h-6" />}
              link="/graph"
            />
            <FeatureCard
              title="AI Tutor Chat"
              description="Ask questions with citations from open textbooks"
              icon={<MessageSquare className="w-6 h-6" />}
              link="/chat"
            />
            <FeatureCard
              title="KG-Aware RAG"
              description="Query expansion using prerequisite concept chains"
              icon={<TrendingUp className="w-6 h-6" />}
              link="/comparison"
            />
            <FeatureCard
              title="Local-First"
              description="Runs on your machine with a local LLM by default"
              icon={<Zap className="w-6 h-6" />}
              link="/about"
            />
            <FeatureCard
              title="Assessment"
              description="Test your mastery with adaptive quizzes and instant remediation"
              icon={<GraduationCap className="w-6 h-6" />}
              link="/assessment"
            />
          </div>
        </div>

        {/* How It Works */}
        <div className="bg-white rounded-lg shadow-md p-8">
          <h3 className="text-2xl font-bold text-gray-900 mb-6 text-center">
            How It Works
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            <Step
              number={1}
              title="Ingest Content"
              description="System ingests OpenStax textbooks, chunking by topic and section"
            />
            <Step
              number={2}
              title="Build Graph"
              description="Relationships (PREREQ, COVERS, RELATED) are extracted and stored in Neo4j"
            />
            <Step
              number={3}
              title="Smart Retrieval"
              description="Questions are answered with KG expansion, hybrid retrieval, and source citations"
            />
          </div>
        </div>

        {/* Attribution */}
        <div className="mt-12 text-center text-sm text-gray-600">
          <p>
            Content adapted from{' '}
            <a
              href="https://openstax.org/"
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary-600 hover:text-primary-700 underline"
            >
              OpenStax
            </a>
            {' '}open textbooks
            {availableSubjectNames.length > 0 && ` (${availableSubjectNames.join(', ')})`}
          </p>
          <p className="mt-1">
            Licensed under{' '}
            <a
              href="https://creativecommons.org/licenses/by/4.0/"
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary-600 hover:text-primary-700 underline"
            >
              CC BY 4.0
            </a>
          </p>
        </div>
      </main>
    </div>
  );
}

// Sub-components

interface StatCardProps {
  title: string;
  value: number;
  icon: React.ReactNode;
  color: 'blue' | 'purple' | 'green';
  description: string;
}

function StatCard({ title, value, icon, color, description }: StatCardProps) {
  const colorClasses = {
    blue: 'bg-blue-50 text-blue-600 border-blue-200',
    purple: 'bg-purple-50 text-purple-600 border-purple-200',
    green: 'bg-green-50 text-green-600 border-green-200',
  };

  return (
    <div className="bg-white rounded-lg shadow-md p-6 border border-gray-200 hover:shadow-lg transition-shadow">
      <div className={`inline-flex p-3 rounded-lg ${colorClasses[color]}`} aria-hidden="true">
        {icon}
      </div>
      <h4 className="mt-4 text-3xl font-bold text-gray-900">
        {value.toLocaleString()}
      </h4>
      <p className="text-sm font-medium text-gray-900 mt-1">{title}</p>
      <p className="text-sm text-gray-500 mt-1">{description}</p>
    </div>
  );
}

interface FeatureCardProps {
  title: string;
  description: string;
  icon: React.ReactNode;
  link: string;
}

function FeatureCard({ title, description, icon, link }: FeatureCardProps) {
  return (
    <Link href={link}>
      <div className="bg-white rounded-lg shadow-md p-6 border border-gray-200 hover:shadow-lg hover:border-primary-300 transition-all cursor-pointer h-full">
        <div className="flex items-center gap-3 mb-3">
          <div className="text-primary-600" aria-hidden="true">{icon}</div>
          <h4 className="text-lg font-semibold text-gray-900">{title}</h4>
        </div>
        <p className="text-sm text-gray-600">{description}</p>
      </div>
    </Link>
  );
}

interface StepProps {
  number: number;
  title: string;
  description: string;
}

function Step({ number, title, description }: StepProps) {
  return (
    <div className="text-center">
      <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-primary-600 text-white font-bold text-xl mb-4">
        {number}
      </div>
      <h4 className="text-lg font-semibold text-gray-900 mb-2">{title}</h4>
      <p className="text-sm text-gray-600">{description}</p>
    </div>
  );
}
