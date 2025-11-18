'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { apiClient } from '@/lib/api-client';
import type { GraphStats } from '@/lib/types';
import { Network, MessageSquare, TrendingUp, Zap } from 'lucide-react';

export default function Home() {
  const [stats, setStats] = useState<GraphStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchStats = async () => {
      try {
        setIsLoading(true);
        const data = await apiClient.getGraphStats();
        setStats(data);
        setError(null);
      } catch (err) {
        console.error('Error fetching stats:', err);
        setError('Unable to load statistics. Using demo data.');
        // Stats will show mock data from API client
      } finally {
        setIsLoading(false);
      }
    };

    fetchStats();
  }, []);

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-purple-50">
      {/* Header */}
      <header className="bg-white shadow-sm border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-3xl font-bold text-gray-900">
                Adaptive Knowledge Graph
              </h1>
              <p className="mt-2 text-gray-600">
                Personalized Learning with AI & Knowledge Graphs
              </p>
            </div>
            <div className="flex gap-4">
              <Link
                href="/graph"
                className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-primary-600 hover:bg-primary-700 transition-colors"
              >
                Explore Graph
              </Link>
              <Link
                href="/chat"
                className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 transition-colors"
              >
                Ask Questions
              </Link>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        {/* Hero Section */}
        <div className="text-center mb-16">
          <h2 className="text-4xl font-extrabold text-gray-900 sm:text-5xl sm:tracking-tight lg:text-6xl">
            Learn Smarter with
            <span className="text-primary-600"> AI-Powered</span> Knowledge Graphs
          </h2>
          <p className="mt-6 max-w-2xl mx-auto text-xl text-gray-500">
            Experience personalized education through knowledge graph-aware RAG,
            local-first LLMs, and adaptive learning algorithms.
          </p>
        </div>

        {/* Statistics Dashboard */}
        <div className="mb-16">
          <h3 className="text-2xl font-bold text-gray-900 mb-6 text-center">
            Knowledge Graph Statistics
          </h3>
          {isLoading ? (
            <div className="flex justify-center items-center h-32">
              <div className="spinner"></div>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-6 sm:grid-cols-3">
              <StatCard
                title="Concepts"
                value={stats?.concept_count ?? 0}
                icon={<Network className="w-8 h-8" />}
                color="blue"
                description="Biology concepts extracted"
              />
              <StatCard
                title="Modules"
                value={stats?.module_count ?? 0}
                icon={<TrendingUp className="w-8 h-8" />}
                color="purple"
                description="OpenStax modules analyzed"
              />
              <StatCard
                title="Relationships"
                value={stats?.relationship_count ?? 0}
                icon={<Zap className="w-8 h-8" />}
                color="green"
                description="Concept relationships mapped"
              />
            </div>
          )}
          {error && (
            <div className="mt-4 p-4 bg-yellow-50 border border-yellow-200 rounded-md">
              <p className="text-sm text-yellow-800 text-center">{error}</p>
            </div>
          )}
        </div>

        {/* Feature Cards */}
        <div className="mb-16">
          <h3 className="text-2xl font-bold text-gray-900 mb-6 text-center">
            Key Features
          </h3>
          <div className="grid grid-cols-1 gap-8 md:grid-cols-2 lg:grid-cols-4">
            <FeatureCard
              title="Knowledge Graph"
              description="Interactive visualization of Biology concepts and their relationships"
              icon={<Network className="w-6 h-6" />}
              link="/graph"
            />
            <FeatureCard
              title="AI Tutor Chat"
              description="Ask questions and get answers with citations from OpenStax"
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
              description="Privacy-focused: All data stays on your machine"
              icon={<Zap className="w-6 h-6" />}
              link="/about"
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
              title="Extract Concepts"
              description="YAKE and KeyBERT extract key biology concepts from OpenStax Biology 2e textbook"
            />
            <Step
              number={2}
              title="Build Graph"
              description="Relationships (PREREQ, COVERS, RELATED) are mined and stored in Neo4j"
            />
            <Step
              number={3}
              title="Smart Retrieval"
              description="Questions are expanded through the graph, retrieving more relevant context for better answers"
            />
          </div>
        </div>

        {/* Attribution */}
        <div className="mt-12 text-center text-sm text-gray-600">
          <p>
            Content adapted from{' '}
            <a
              href="https://openstax.org/details/books/biology-2e"
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary-600 hover:text-primary-700 underline"
            >
              OpenStax Biology 2e
            </a>
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
      <div className={`inline-flex p-3 rounded-lg ${colorClasses[color]}`}>
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
          <div className="text-primary-600">{icon}</div>
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
