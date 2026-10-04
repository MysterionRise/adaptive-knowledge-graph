import type { Metadata } from 'next';
import { Shield, Database, Cpu, Globe } from 'lucide-react';

export const metadata: Metadata = {
  title: 'About',
  description: 'What the Adaptive Knowledge Graph project is, how it works and what it is built with.',
};

export default function AboutPage() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-purple-50">
      {/* Header */}
      <header className="bg-white shadow-sm border-b border-gray-200">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <h1 className="text-3xl font-bold text-gray-900">About</h1>
          <p className="mt-2 text-gray-600">
            Learn more about the Adaptive Knowledge Graph project
          </p>
        </div>
      </header>

      {/* Main Content */}
      <main id="main-content" className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        {/* Overview */}
        <div className="bg-white rounded-lg shadow-md p-8 border border-gray-200">
          <h2 className="text-2xl font-bold text-gray-900 mb-4">Overview</h2>
          <p className="text-gray-700 leading-relaxed mb-4">
            The Adaptive Knowledge Graph is a proof-of-concept for personalized
            education using knowledge graphs, local LLMs, and adaptive learning
            algorithms.
          </p>
          <p className="text-gray-700 leading-relaxed">
            It works with openly licensed OpenStax textbooks and supports several
            subjects: each subject is configured in the backend and becomes available
            once its textbook content has been ingested into the knowledge graph.
          </p>
        </div>

        {/* Key Features */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <FeatureCard
            icon={<Shield className="w-8 h-8" />}
            title="Local-First"
            description="By default the API, the databases and the language model all run on your own machine, so questions and learner progress stay there. A remote LLM provider is only used if you configure one."
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
            description="Quantized open models served by Ollama. Runs on an ordinary laptop or workstation; a GPU makes answers faster but is not required."
            color="green"
          />
          <FeatureCard
            icon={<Globe className="w-8 h-8" />}
            title="Open Source"
            description="MIT-licensed code built on OpenStax content (CC BY 4.0). Transparent, auditable, and extensible for research."
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
                <li>• FastAPI REST API, with server-sent events for streamed answers</li>
                <li>• Neo4j for knowledge graph storage</li>
                <li>• OpenSearch for vector search</li>
                <li>• BGE-M3 embeddings</li>
                <li>• Local LLMs via Ollama (Llama 3.1 8B by default)</li>
              </ul>
            </div>
            <div>
              <h3 className="font-semibold text-gray-900 mb-3">Frontend</h3>
              <ul className="space-y-2 text-sm text-gray-700">
                <li>• Next.js and React with TypeScript</li>
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
              href="https://openstax.org/"
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-blue-900"
            >
              OpenStax
            </a>{' '}
            textbooks, licensed under{' '}
            <a
              href="https://creativecommons.org/licenses/by/4.0/"
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-blue-900"
            >
              CC BY 4.0
            </a>
            . Each answer names the book it is based on.
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
      <div className={`inline-flex p-3 rounded-lg ${colorClasses[color]} mb-4`} aria-hidden="true">
        {icon}
      </div>
      <h3 className="text-lg font-semibold text-gray-900 mb-2">{title}</h3>
      <p className="text-sm text-gray-600">{description}</p>
    </div>
  );
}
