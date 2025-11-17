'use client';

import { useRouter } from 'next/navigation';
import { ArrowLeft, Shield, Database, Cpu, Globe } from 'lucide-react';

export default function AboutPage() {
  const router = useRouter();

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-purple-50">
      {/* Header */}
      <header className="bg-white shadow-sm border-b border-gray-200">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex items-center gap-4">
            <button
              onClick={() => router.push('/')}
              className="text-gray-600 hover:text-gray-900"
              aria-label="Back to home"
            >
              <ArrowLeft className="w-6 h-6" />
            </button>
            <div>
              <h1 className="text-3xl font-bold text-gray-900">About</h1>
              <p className="mt-2 text-gray-600">
                Learn more about the Adaptive Knowledge Graph project
              </p>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        {/* Overview */}
        <div className="bg-white rounded-lg shadow-md p-8 border border-gray-200">
          <h2 className="text-2xl font-bold text-gray-900 mb-4">Overview</h2>
          <p className="text-gray-700 leading-relaxed mb-4">
            The Adaptive Knowledge Graph is a proof-of-concept for personalized
            education using knowledge graphs, local LLMs, and adaptive learning
            algorithms.
          </p>
          <p className="text-gray-700 leading-relaxed">
            Built on OpenStax Biology 2e content, this system demonstrates how
            AI can provide personalized, privacy-focused tutoring at scale.
          </p>
        </div>

        {/* Key Features */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <FeatureCard
            icon={<Shield className="w-8 h-8" />}
            title="Privacy-First"
            description="All processing happens locally. No student data leaves your machine. FERPA and GDPR compliant by design."
            color="blue"
          />
          <FeatureCard
            icon={<Database className="w-8 h-8" />}
            title="Knowledge Graph"
            description="Concepts and relationships extracted from textbooks, enabling smarter retrieval and prerequisite tracking."
            color="purple"
          />
          <FeatureCard
            icon={<Cpu className="w-8 h-8" />}
            title="Local LLMs"
            description="Runs on commodity hardware (RTX 4070) with 4-bit quantized models. No cloud dependencies."
            color="green"
          />
          <FeatureCard
            icon={<Globe className="w-8 h-8" />}
            title="Open Source"
            description="Built with OpenStax content (CC BY 4.0). Transparent, auditable, and extensible for research."
            color="orange"
          />
        </div>

        {/* Technology Stack */}
        <div className="bg-white rounded-lg shadow-md p-8 border border-gray-200">
          <h2 className="text-2xl font-bold text-gray-900 mb-6">
            Technology Stack
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <h3 className="font-semibold text-gray-900 mb-3">Backend</h3>
              <ul className="space-y-2 text-sm text-gray-700">
                <li>• FastAPI for REST/WebSocket API</li>
                <li>• Neo4j for knowledge graph storage</li>
                <li>• Qdrant for vector search</li>
                <li>• BGE-M3 embeddings</li>
                <li>• Llama 3.1 / Qwen 2.5 (via Ollama)</li>
              </ul>
            </div>
            <div>
              <h3 className="font-semibold text-gray-900 mb-3">Frontend</h3>
              <ul className="space-y-2 text-sm text-gray-700">
                <li>• Next.js 14 with TypeScript</li>
                <li>• Tailwind CSS for styling</li>
                <li>• Cytoscape.js for graph visualization</li>
                <li>• Jest & Playwright for testing</li>
              </ul>
            </div>
          </div>
        </div>

        {/* Attribution */}
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-6">
          <h2 className="text-lg font-bold text-blue-900 mb-3">
            Content Attribution
          </h2>
          <p className="text-sm text-blue-800 mb-2">
            This project uses content from{' '}
            <a
              href="https://openstax.org/details/books/biology-2e"
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-blue-900"
            >
              OpenStax Biology 2e
            </a>
            , licensed under{' '}
            <a
              href="https://creativecommons.org/licenses/by/4.0/"
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-blue-900"
            >
              CC BY 4.0
            </a>
            .
          </p>
          <p className="text-xs text-blue-700">
            OpenStax™ is a trademark of Rice University. This project is not
            affiliated with or endorsed by OpenStax.
          </p>
        </div>

        {/* License */}
        <div className="bg-white rounded-lg shadow-md p-8 border border-gray-200">
          <h2 className="text-2xl font-bold text-gray-900 mb-4">License</h2>
          <p className="text-gray-700 leading-relaxed">
            This software is licensed under the MIT License. See the LICENSE
            file in the repository for details.
          </p>
        </div>
      </main>
    </div>
  );
}

interface FeatureCardProps {
  icon: React.ReactNode;
  title: string;
  description: string;
  color: 'blue' | 'purple' | 'green' | 'orange';
}

function FeatureCard({ icon, title, description, color }: FeatureCardProps) {
  const colorClasses = {
    blue: 'bg-blue-50 text-blue-600 border-blue-200',
    purple: 'bg-purple-50 text-purple-600 border-purple-200',
    green: 'bg-green-50 text-green-600 border-green-200',
    orange: 'bg-orange-50 text-orange-600 border-orange-200',
  };

  return (
    <div className="bg-white rounded-lg shadow-md p-6 border border-gray-200">
      <div className={`inline-flex p-3 rounded-lg ${colorClasses[color]} mb-4`}>
        {icon}
      </div>
      <h3 className="text-lg font-semibold text-gray-900 mb-2">{title}</h3>
      <p className="text-sm text-gray-600">{description}</p>
    </div>
  );
}
