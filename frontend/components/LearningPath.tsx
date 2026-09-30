'use client';

import { useRouter } from 'next/navigation';
import { apiClient } from '@/lib/api-client';
import { describeError } from '@/lib/api-errors';
import { masteryLevelOf } from '@/lib/mastery';
import { useAppStore } from '@/lib/store';
import type { LearningPathResponse } from '@/lib/types';
import { useApiQuery } from '@/lib/useApiQuery';
import ErrorMessage from './ErrorMessage';
import {
  CheckCircle2,
  ArrowDown,
  BookOpen,
  MessageSquare,
  Loader2,
  Trophy,
  Target,
} from 'lucide-react';

// Prerequisite steps to follow back from the target concept
const MAX_PATH_DEPTH = 5;

interface LearningPathStep {
  name: string;
  /** PREREQ steps before the target (0 = the target itself). */
  depth: number;
  isTarget: boolean;
}

interface LearningPathProps {
  conceptName: string;
  onConceptClick?: (conceptName: string) => void;
  className?: string;
}

type MasteryStatus = 'complete' | 'current' | 'pending';

/** Prerequisites in learning order (furthest from the target first), then the target. */
function buildSteps(path: LearningPathResponse, conceptName: string): LearningPathStep[] {
  const target = path.target_concept || conceptName;
  const prerequisites = path.prerequisites
    .filter((prereq) => prereq.name.toLowerCase() !== target.toLowerCase())
    .sort((a, b) => b.depth - a.depth || b.importance - a.importance)
    .map((prereq) => ({ name: prereq.name, depth: prereq.depth, isTarget: false }));
  return prerequisites.length > 0
    ? [...prerequisites, { name: target, depth: 0, isTarget: true }]
    : [];
}

function depthLabel(step: LearningPathStep): string {
  if (step.isTarget) return 'Target concept';
  return step.depth === 1 ? 'Direct prerequisite' : `${step.depth} steps before the target`;
}

const getMasteryStatus = (mastery: number): MasteryStatus => {
  if (mastery >= 0.7) return 'complete';
  if (mastery >= 0.3) return 'current';
  return 'pending';
};

const getMasteryColor = (status: MasteryStatus) => {
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

export default function LearningPath({
  conceptName,
  onConceptClick,
  className = '',
}: LearningPathProps) {
  const router = useRouter();
  const currentSubject = useAppStore((state) => state.currentSubject);
  const masteryMap = useAppStore((state) => state.masteryMap);
  const concept = conceptName.trim();

  const pathQuery = useApiQuery(
    concept ? `learning-path:${currentSubject}:${concept}` : null,
    (signal) => apiClient.getLearningPath(concept, MAX_PATH_DEPTH, currentSubject, { signal })
  );

  const handleAskTutor = (name: string) => {
    router.push(`/chat?question=${encodeURIComponent(`Explain ${name}`)}`);
  };

  const handlePractice = (name: string) => {
    router.push(`/assessment?topic=${encodeURIComponent(name)}`);
  };

  if (!concept) {
    return (
      <div className={`flex flex-col items-center justify-center p-8 ${className}`}>
        <Target className="w-8 h-8 text-gray-400 mb-3" aria-hidden="true" />
        <p className="text-sm text-gray-600">Choose a concept to see its learning path.</p>
      </div>
    );
  }

  if (pathQuery.isLoading) {
    return (
      <div className={`flex flex-col items-center justify-center p-8 ${className}`} role="status">
        <Loader2 className="w-8 h-8 animate-spin text-blue-600 mb-3" aria-hidden="true" />
        <p className="text-sm text-gray-600">Loading learning path...</p>
      </div>
    );
  }

  if (pathQuery.error || !pathQuery.data) {
    return (
      <ErrorMessage
        className={className}
        title="Unable to load learning path."
        message={describeError(pathQuery.error)}
        onRetry={pathQuery.retry}
      />
    );
  }

  const steps = buildSteps(pathQuery.data, concept);

  if (steps.length === 0) {
    return (
      <div className={`flex flex-col items-center justify-center p-8 ${className}`}>
        <Target className="w-8 h-8 text-gray-400 mb-3" aria-hidden="true" />
        <p className="text-sm text-gray-600">No prerequisite path found for this concept.</p>
      </div>
    );
  }

  const masteryLevels = steps.map((step) => masteryLevelOf(masteryMap, step.name));

  return (
    <div className={`relative ${className}`}>
      {/* Header */}
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-2">
          <Trophy className="w-5 h-5 text-amber-500" aria-hidden="true" />
          <h3 className="font-bold text-gray-900">Learning Path</h3>
        </div>
        <p className="text-sm text-gray-600">
          Master these concepts in order to understand{' '}
          <span className="font-semibold text-blue-600">{concept}</span>
        </p>
      </div>

      {/* Timeline */}
      <div className="relative">
        {/* Vertical line */}
        <div
          className="absolute left-6 top-0 bottom-0 w-0.5 bg-gradient-to-b from-gray-200 via-blue-200 to-emerald-200"
          aria-hidden="true"
        />

        <ol aria-label={`Learning path to ${concept}`}>
          {steps.map((step, idx) => {
            const mastery = masteryLevels[idx];
            const status = getMasteryStatus(mastery);
            const isLast = idx === steps.length - 1;
            const isTarget = step.isTarget;
  
            return (
              <li key={step.name} className="relative pl-16 pb-6 last:pb-0">
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
                  aria-hidden="true"
                >
                  {status === 'complete' && !isTarget && (
                    <CheckCircle2 className="w-3 h-3 text-white" />
                  )}
                  {isTarget && <Target className="w-3 h-3 text-white" />}
                </div>
  
                {/* Arrow connector */}
                {!isLast && (
                  <ArrowDown
                    className="absolute left-[17px] bottom-0 w-3 h-3 text-gray-300"
                    aria-hidden="true"
                  />
                )}
  
                {/* Concept card: the title button covers the card, the actions sit above it */}
                <div
                  className={`relative p-4 rounded-lg border-2 transition-all hover:shadow-md ${
                    onConceptClick ? 'cursor-pointer' : ''
                  } ${isTarget ? 'border-amber-300 bg-amber-50' : getMasteryColor(status)}`}
                >
                  <div className="flex items-start justify-between gap-3 mb-3">
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <h4 className={`font-semibold ${isTarget ? 'text-amber-900' : 'text-gray-900'}`}>
                          {onConceptClick ? (
                            <button
                              type="button"
                              onClick={() => onConceptClick(step.name)}
                              className="text-left after:absolute after:inset-0 after:rounded-lg after:content-[''] focus:outline-none focus-visible:after:ring-2 focus-visible:after:ring-blue-500"
                            >
                              {step.name}
                            </button>
                          ) : (
                            step.name
                          )}
                        </h4>
                        {isTarget && (
                          <span className="px-2 py-0.5 text-xs font-medium bg-amber-200 text-amber-800 rounded-full">
                            Target
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-gray-500 mt-1">{depthLabel(step)}</p>
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
                  <div className="h-2 bg-gray-200 rounded-full overflow-hidden mb-3" aria-hidden="true">
                    <div
                      className={`h-full transition-all duration-500 ${getProgressBarColor(mastery)}`}
                      style={{ width: `${mastery * 100}%` }}
                    />
                  </div>
  
                  {/* Actions */}
                  <div className="relative z-10 flex gap-2">
                    <button
                      type="button"
                      onClick={() => handleAskTutor(step.name)}
                      aria-label={`Ask Tutor about ${step.name}`}
                      className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-blue-700 bg-blue-100 rounded-md hover:bg-blue-200 transition-colors"
                    >
                      <MessageSquare className="w-3 h-3" aria-hidden="true" />
                      Ask Tutor
                    </button>
                    <button
                      type="button"
                      onClick={() => handlePractice(step.name)}
                      aria-label={`Practice ${step.name}`}
                      className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-purple-700 bg-purple-100 rounded-md hover:bg-purple-200 transition-colors"
                    >
                      <BookOpen className="w-3 h-3" aria-hidden="true" />
                      Practice
                    </button>
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
      </div>

      {/* Summary */}
      <div className="mt-6 p-4 bg-gray-50 rounded-lg border border-gray-200">
        <div className="flex items-center justify-between text-sm">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-1.5">
              <div className="w-3 h-3 rounded-full bg-emerald-500" aria-hidden="true" />
              <span className="text-gray-600">Mastered</span>
              <span className="font-semibold text-gray-900">
                {masteryLevels.filter((m) => m >= 0.7).length}
              </span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-3 h-3 rounded-full bg-blue-500" aria-hidden="true" />
              <span className="text-gray-600">In Progress</span>
              <span className="font-semibold text-gray-900">
                {masteryLevels.filter((m) => m >= 0.3 && m < 0.7).length}
              </span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-3 h-3 rounded-full bg-gray-300" aria-hidden="true" />
              <span className="text-gray-600">To Learn</span>
              <span className="font-semibold text-gray-900">
                {masteryLevels.filter((m) => m < 0.3).length}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
