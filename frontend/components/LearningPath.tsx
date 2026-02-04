'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiClient } from '@/lib/api-client';
import { useAppStore } from '@/lib/store';
import {
  CheckCircle2,
  Circle,
  ArrowDown,
  BookOpen,
  MessageSquare,
  Loader2,
  AlertCircle,
  Trophy,
  Target,
} from 'lucide-react';

interface LearningPathNode {
  name: string;
  depth: number;
  importance?: number;
}

interface LearningPathResponse {
  concept: string;
  path: LearningPathNode[];
  depth: number;
}

interface LearningPathProps {
  conceptName: string;
  onConceptClick?: (conceptName: string) => void;
  className?: string;
}

export default function LearningPath({
  conceptName,
  onConceptClick,
  className = '',
}: LearningPathProps) {
  const router = useRouter();
  const [pathData, setPathData] = useState<LearningPathResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const { getMastery, masteryMap } = useAppStore();

  useEffect(() => {
    const fetchLearningPath = async () => {
      if (!conceptName) return;

      setIsLoading(true);
      setError(null);

      try {
        const response = await fetch(
          `/api/v1/learning-path/${encodeURIComponent(conceptName)}?max_depth=5`
        );
        if (!response.ok) {
          throw new Error('Failed to fetch learning path');
        }
        const data = await response.json();
        setPathData(data);
      } catch (err) {
        console.error('Error fetching learning path:', err);
        setError('Unable to load learning path. Please try again.');
      } finally {
        setIsLoading(false);
      }
    };

    fetchLearningPath();
  }, [conceptName]);

  const handleAskTutor = (concept: string) => {
    router.push(`/chat?question=${encodeURIComponent(`Explain ${concept}`)}`);
  };

  const getMasteryStatus = (concept: string): 'complete' | 'current' | 'pending' => {
    const mastery = getMastery(concept);
    if (mastery >= 0.7) return 'complete';
    if (mastery >= 0.3) return 'current';
    return 'pending';
  };

  const getMasteryColor = (status: 'complete' | 'current' | 'pending') => {
    switch (status) {
      case 'complete':
        return 'text-emerald-500 bg-emerald-50 border-emerald-200';
      case 'current':
        return 'text-blue-500 bg-blue-50 border-blue-200';
      case 'pending':
        return 'text-gray-400 bg-gray-50 border-gray-200';
    }
  };

  const getProgressBarColor = (mastery: number) => {
    if (mastery >= 0.7) return 'bg-emerald-500';
    if (mastery >= 0.4) return 'bg-blue-500';
    return 'bg-gray-300';
  };

  if (isLoading) {
    return (
      <div className={`flex flex-col items-center justify-center p-8 ${className}`}>
        <Loader2 className="w-8 h-8 animate-spin text-blue-600 mb-3" />
        <p className="text-sm text-gray-600">Loading learning path...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className={`flex flex-col items-center justify-center p-8 ${className}`}>
        <AlertCircle className="w-8 h-8 text-red-500 mb-3" />
        <p className="text-sm text-red-600">{error}</p>
      </div>
    );
  }

  if (!pathData || pathData.path.length === 0) {
    return (
      <div className={`flex flex-col items-center justify-center p-8 ${className}`}>
        <Target className="w-8 h-8 text-gray-400 mb-3" />
        <p className="text-sm text-gray-600">No prerequisite path found for this concept.</p>
      </div>
    );
  }

  // Sort path by depth (prerequisites first)
  const sortedPath = [...pathData.path].sort((a, b) => b.depth - a.depth);

  return (
    <div className={`relative ${className}`}>
      {/* Header */}
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-2">
          <Trophy className="w-5 h-5 text-amber-500" />
          <h3 className="font-bold text-gray-900">Learning Path</h3>
        </div>
        <p className="text-sm text-gray-600">
          Master these concepts in order to understand{' '}
          <span className="font-semibold text-blue-600">{conceptName}</span>
        </p>
      </div>

      {/* Timeline */}
      <div className="relative">
        {/* Vertical line */}
        <div className="absolute left-6 top-0 bottom-0 w-0.5 bg-gradient-to-b from-gray-200 via-blue-200 to-emerald-200" />

        {sortedPath.map((node, idx) => {
          const status = getMasteryStatus(node.name);
          const mastery = getMastery(node.name);
          const isLast = idx === sortedPath.length - 1;
          const isTarget = node.name === conceptName;

          return (
            <div key={node.name} className="relative pl-16 pb-6 last:pb-0">
              {/* Node indicator */}
              <div
                className={`absolute left-4 w-5 h-5 rounded-full border-2 flex items-center justify-center transition-all ${
                  isTarget
                    ? 'bg-amber-500 border-amber-400'
                    : status === 'complete'
                    ? 'bg-emerald-500 border-emerald-400'
                    : status === 'current'
                    ? 'bg-blue-500 border-blue-400'
                    : 'bg-white border-gray-300'
                }`}
              >
                {status === 'complete' && !isTarget && (
                  <CheckCircle2 className="w-3 h-3 text-white" />
                )}
                {isTarget && <Target className="w-3 h-3 text-white" />}
              </div>

              {/* Arrow connector */}
              {!isLast && (
                <ArrowDown className="absolute left-[17px] bottom-0 w-3 h-3 text-gray-300" />
              )}

              {/* Concept card */}
              <div
                className={`p-4 rounded-lg border-2 transition-all hover:shadow-md cursor-pointer ${
                  isTarget
                    ? 'border-amber-300 bg-amber-50'
                    : getMasteryColor(status)
                }`}
                onClick={() => onConceptClick?.(node.name)}
              >
                <div className="flex items-start justify-between gap-3 mb-3">
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <h4 className={`font-semibold ${isTarget ? 'text-amber-900' : 'text-gray-900'}`}>
                        {node.name}
                      </h4>
                      {isTarget && (
                        <span className="px-2 py-0.5 text-xs font-medium bg-amber-200 text-amber-800 rounded-full">
                          Target
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-gray-500 mt-1">
                      Depth: {node.depth} {node.depth === 0 ? '(direct prerequisite)' : ''}
                    </p>
                  </div>

                  {/* Mastery percentage */}
                  <div className="text-right">
                    <span className={`text-lg font-bold ${
                      mastery >= 0.7 ? 'text-emerald-600' :
                      mastery >= 0.4 ? 'text-blue-600' : 'text-gray-400'
                    }`}>
                      {Math.round(mastery * 100)}%
                    </span>
                    <p className="text-xs text-gray-500">mastery</p>
                  </div>
                </div>

                {/* Progress bar */}
                <div className="h-2 bg-gray-200 rounded-full overflow-hidden mb-3">
                  <div
                    className={`h-full transition-all duration-500 ${getProgressBarColor(mastery)}`}
                    style={{ width: `${mastery * 100}%` }}
                  />
                </div>

                {/* Actions */}
                <div className="flex gap-2">
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handleAskTutor(node.name);
                    }}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-blue-700 bg-blue-100 rounded-md hover:bg-blue-200 transition-colors"
                  >
                    <MessageSquare className="w-3 h-3" />
                    Ask Tutor
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      router.push(`/quiz?topic=${encodeURIComponent(node.name)}`);
                    }}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-purple-700 bg-purple-100 rounded-md hover:bg-purple-200 transition-colors"
                  >
                    <BookOpen className="w-3 h-3" />
                    Practice
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Summary */}
      <div className="mt-6 p-4 bg-gray-50 rounded-lg border border-gray-200">
        <div className="flex items-center justify-between text-sm">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-1.5">
              <div className="w-3 h-3 rounded-full bg-emerald-500" />
              <span className="text-gray-600">Mastered</span>
              <span className="font-semibold text-gray-900">
                {sortedPath.filter(n => getMastery(n.name) >= 0.7).length}
              </span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-3 h-3 rounded-full bg-blue-500" />
              <span className="text-gray-600">In Progress</span>
              <span className="font-semibold text-gray-900">
                {sortedPath.filter(n => getMastery(n.name) >= 0.3 && getMastery(n.name) < 0.7).length}
              </span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-3 h-3 rounded-full bg-gray-300" />
              <span className="text-gray-600">To Learn</span>
              <span className="font-semibold text-gray-900">
                {sortedPath.filter(n => getMastery(n.name) < 0.3).length}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
