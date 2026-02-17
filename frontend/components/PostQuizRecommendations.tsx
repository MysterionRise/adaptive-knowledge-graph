'use client';

import { useState } from 'react';
import { AlertCircle, TrendingUp, BookOpen, MessageSquare, ChevronDown, ChevronUp, Sparkles, Target } from 'lucide-react';

interface ReadingMaterial {
  text: string;
  section?: string;
  module_title?: string;
  relevance_score?: number;
}

interface ConceptRecommendation {
  name: string;
  importance?: number;
  mastery?: number;
  relationship_type?: string;
}

interface RemediationBlock {
  concept: string;
  prerequisites: ConceptRecommendation[];
  reading_materials: ReadingMaterial[];
}

interface AdvancementBlock {
  concept: string;
  advanced_topics: ConceptRecommendation[];
  deep_dive_content?: string;
}

interface RecommendationResponse {
  path_type: string;
  score_pct: number;
  remediation: RemediationBlock[];
  advancement: AdvancementBlock[];
  summary: string;
}

interface PostQuizRecommendationsProps {
  recommendations: RecommendationResponse | null;
  isLoading: boolean;
  error: string | null;
  onPractice: (concept: string) => void;
  onAskTutor: (concept: string) => void;
}

function MasteryBar({ mastery }: { mastery?: number }) {
  const value = mastery ?? 0.3;
  const pct = Math.round(value * 100);
  const color = value >= 0.7 ? 'bg-emerald-500' : value >= 0.4 ? 'bg-blue-500' : 'bg-gray-300';

  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-gray-200 rounded-full overflow-hidden">
        <div className={`h-full transition-all duration-500 ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-medium text-gray-500 w-8 text-right">{pct}%</span>
    </div>
  );
}

function ReadingCard({ material }: { material: ReadingMaterial }) {
  const [expanded, setExpanded] = useState(false);
  const preview = material.text.length > 200 ? material.text.slice(0, 200) + '...' : material.text;

  return (
    <div className="p-3 bg-white rounded-lg border border-gray-200">
      <div className="flex items-center gap-2 mb-1">
        <BookOpen className="w-3.5 h-3.5 text-gray-400" />
        {material.module_title && (
          <span className="text-xs font-medium text-gray-600">{material.module_title}</span>
        )}
        {material.section && (
          <span className="text-xs text-gray-400">&middot; {material.section}</span>
        )}
      </div>
      <p className="text-sm text-gray-700 italic leading-relaxed">
        &ldquo;{expanded ? material.text : preview}&rdquo;
      </p>
      {material.text.length > 200 && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-1 mt-1 text-xs text-blue-600 hover:text-blue-700"
        >
          {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          {expanded ? 'Show less' : 'Read more'}
        </button>
      )}
    </div>
  );
}

export default function PostQuizRecommendations({
  recommendations,
  isLoading,
  error,
  onPractice,
  onAskTutor,
}: PostQuizRecommendationsProps) {
  if (isLoading) {
    return (
      <div className="mt-6 p-6 bg-gray-50 rounded-xl border border-gray-200 animate-pulse">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-5 h-5 bg-gray-300 rounded" />
          <div className="h-5 w-48 bg-gray-300 rounded" />
        </div>
        <div className="space-y-3">
          <div className="h-4 bg-gray-200 rounded w-3/4" />
          <div className="h-20 bg-gray-200 rounded" />
          <div className="h-20 bg-gray-200 rounded" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="mt-6 p-4 bg-red-50 rounded-xl border border-red-200">
        <div className="flex items-center gap-2 text-red-700">
          <AlertCircle className="w-4 h-4" />
          <span className="text-sm">{error}</span>
        </div>
      </div>
    );
  }

  if (!recommendations) return null;

  return (
    <div className="mt-6 space-y-6">
      {/* Summary */}
      <p className="text-sm text-gray-600 bg-blue-50 p-3 rounded-lg border border-blue-100">
        {recommendations.summary}
      </p>

      {/* Remediation Section */}
      {recommendations.remediation.length > 0 && (
        <div className="bg-gradient-to-br from-red-50 to-orange-50 rounded-xl border border-red-200 overflow-hidden">
          <div className="p-4 border-b border-red-100">
            <div className="flex items-center gap-2">
              <AlertCircle className="w-5 h-5 text-red-500" />
              <h4 className="font-bold text-red-900">Areas to Strengthen</h4>
            </div>
          </div>

          <div className="p-4 space-y-5">
            {recommendations.remediation.map((block) => (
              <div key={block.concept}>
                <h5 className="font-semibold text-gray-900 mb-3">{block.concept}</h5>

                {/* Prerequisites */}
                {block.prerequisites.length > 0 && (
                  <div className="mb-3">
                    <p className="text-xs uppercase font-bold text-gray-400 mb-2">Prerequisites to Review</p>
                    <div className="space-y-2">
                      {block.prerequisites.map((prereq) => (
                        <div
                          key={prereq.name}
                          className="p-3 bg-white rounded-lg border border-red-100"
                        >
                          <div className="flex items-start justify-between gap-3 mb-2">
                            <span className="text-sm font-medium text-gray-900">{prereq.name}</span>
                            <span className="text-xs text-gray-400 shrink-0">
                              {prereq.relationship_type === 'PREREQ' ? 'Prerequisite' : 'Related'}
                            </span>
                          </div>
                          <MasteryBar mastery={prereq.mastery} />
                          <div className="flex gap-2 mt-2">
                            <button
                              onClick={() => onPractice(prereq.name)}
                              className="flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-purple-700 bg-purple-100 rounded-md hover:bg-purple-200 transition-colors"
                            >
                              <Target className="w-3 h-3" />
                              Practice This
                            </button>
                            <button
                              onClick={() => onAskTutor(prereq.name)}
                              className="flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-blue-700 bg-blue-100 rounded-md hover:bg-blue-200 transition-colors"
                            >
                              <MessageSquare className="w-3 h-3" />
                              Ask Tutor
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Reading Materials */}
                {block.reading_materials.length > 0 && (
                  <div>
                    <p className="text-xs uppercase font-bold text-gray-400 mb-2">Recommended Reading</p>
                    <div className="space-y-2">
                      {block.reading_materials.map((material, idx) => (
                        <ReadingCard key={idx} material={material} />
                      ))}
                    </div>
                  </div>
                )}

                {/* Fallback: no prereqs and no reading */}
                {block.prerequisites.length === 0 && block.reading_materials.length === 0 && (
                  <p className="text-sm text-gray-500 italic">
                    No prerequisite path found. Try asking the tutor for guidance on this topic.
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Advancement Section */}
      {recommendations.advancement.length > 0 && (
        <div className="bg-gradient-to-br from-green-50 to-emerald-50 rounded-xl border border-green-200 overflow-hidden">
          <div className="p-4 border-b border-green-100">
            <div className="flex items-center gap-2">
              <TrendingUp className="w-5 h-5 text-green-600" />
              <h4 className="font-bold text-green-900">Ready to Advance</h4>
            </div>
          </div>

          <div className="p-4 space-y-5">
            {recommendations.advancement.map((block) => (
              <div key={block.concept}>
                <h5 className="font-semibold text-gray-900 mb-3">{block.concept}</h5>

                {/* Advanced Topics */}
                {block.advanced_topics.length > 0 && (
                  <div className="mb-3">
                    <p className="text-xs uppercase font-bold text-gray-400 mb-2">Explore Next</p>
                    <div className="flex flex-wrap gap-2">
                      {block.advanced_topics.map((adv) => (
                        <button
                          key={adv.name}
                          onClick={() => onPractice(adv.name)}
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-green-800 bg-green-100 rounded-full border border-green-200 hover:bg-green-200 transition-colors"
                        >
                          {adv.name}
                          {adv.mastery !== undefined && adv.mastery !== null && (
                            <span className="text-xs text-green-600">
                              ({Math.round(adv.mastery * 100)}%)
                            </span>
                          )}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {block.advanced_topics.length === 0 && (
                  <p className="text-sm text-green-700 mb-3">
                    You&apos;ve reached the frontier! Keep exploring related topics.
                  </p>
                )}

                {/* Deep Dive Content */}
                {block.deep_dive_content && (
                  <div className="p-4 bg-white rounded-lg border border-green-200">
                    <div className="flex items-center gap-2 mb-2">
                      <Sparkles className="w-4 h-4 text-amber-500" />
                      <span className="text-xs uppercase font-bold text-gray-400">Deep Dive</span>
                    </div>
                    <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-line">
                      {block.deep_dive_content}
                    </p>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
