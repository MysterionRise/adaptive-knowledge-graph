'use client';

import { Zap, TrendingUp, Target } from 'lucide-react';

interface MasteryIndicatorProps {
  mastery: number; // 0.0 - 1.0
  targetDifficulty: 'easy' | 'medium' | 'hard';
  topic?: string;
  showAdaptingMessage?: boolean;
  compact?: boolean;
}

/**
 * Visual indicator showing student's mastery level and target difficulty.
 * Used in adaptive quiz UI to show personalization.
 */
export default function MasteryIndicator({
  mastery,
  targetDifficulty,
  topic,
  showAdaptingMessage = true,
  compact = false,
}: MasteryIndicatorProps) {
  const percentage = Math.round(mastery * 100);

  // Color gradient based on mastery: Red (0-40%) -> Yellow (40-70%) -> Green (70-100%)
  const getColor = () => {
    if (mastery < 0.4) return { bg: 'bg-red-500', text: 'text-red-700', light: 'bg-red-100' };
    if (mastery <= 0.7) return { bg: 'bg-yellow-500', text: 'text-yellow-700', light: 'bg-yellow-100' };
    return { bg: 'bg-green-500', text: 'text-green-700', light: 'bg-green-100' };
  };

  const getDifficultyBadge = () => {
    const badges = {
      easy: { bg: 'bg-green-100', text: 'text-green-700', border: 'border-green-300' },
      medium: { bg: 'bg-yellow-100', text: 'text-yellow-700', border: 'border-yellow-300' },
      hard: { bg: 'bg-red-100', text: 'text-red-700', border: 'border-red-300' },
    };
    return badges[targetDifficulty];
  };

  const color = getColor();
  const diffBadge = getDifficultyBadge();

  if (compact) {
    return (
      <div className="flex items-center gap-2">
        {/* Compact circular progress */}
        <div className="relative w-8 h-8">
          <svg className="w-full h-full transform -rotate-90">
            <circle
              cx="16"
              cy="16"
              r="12"
              strokeWidth="3"
              className="stroke-gray-200 fill-none"
            />
            <circle
              cx="16"
              cy="16"
              r="12"
              strokeWidth="3"
              className={`fill-none ${color.bg.replace('bg-', 'stroke-')}`}
              style={{
                strokeDasharray: 75.4,
                strokeDashoffset: 75.4 - (75.4 * mastery),
                strokeLinecap: 'round',
              }}
            />
          </svg>
          <span className="absolute inset-0 flex items-center justify-center text-xs font-medium">
            {percentage}%
          </span>
        </div>

        {/* Difficulty badge */}
        <span className={`px-2 py-0.5 text-xs font-medium rounded-full border ${diffBadge.bg} ${diffBadge.text} ${diffBadge.border}`}>
          {targetDifficulty.charAt(0).toUpperCase() + targetDifficulty.slice(1)}
        </span>
      </div>
    );
  }

  return (
    <div className="bg-gradient-to-r from-blue-50 to-indigo-50 rounded-lg p-4 border border-blue-100">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Target className="w-5 h-5 text-blue-600" />
          <span className="font-medium text-gray-800">
            {showAdaptingMessage ? 'Personalized for You' : 'Your Progress'}
          </span>
        </div>

        {showAdaptingMessage && (
          <div className="flex items-center gap-1 text-sm text-blue-600">
            <Zap className="w-4 h-4" />
            <span>Adapting</span>
          </div>
        )}
      </div>

      <div className="flex items-center gap-4">
        {/* Circular progress */}
        <div className="relative w-16 h-16 flex-shrink-0">
          <svg className="w-full h-full transform -rotate-90">
            <circle
              cx="32"
              cy="32"
              r="26"
              strokeWidth="6"
              className="stroke-gray-200 fill-none"
            />
            <circle
              cx="32"
              cy="32"
              r="26"
              strokeWidth="6"
              className={`fill-none transition-all duration-500 ${color.bg.replace('bg-', 'stroke-')}`}
              style={{
                strokeDasharray: 163.4,
                strokeDashoffset: 163.4 - (163.4 * mastery),
                strokeLinecap: 'round',
              }}
            />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-lg font-bold text-gray-900">{percentage}%</span>
          </div>
        </div>

        {/* Info section */}
        <div className="flex-1 min-w-0">
          {topic && (
            <p className="text-sm text-gray-600 truncate mb-1">
              Topic: <span className="font-medium text-gray-800">{topic}</span>
            </p>
          )}

          <div className="flex items-center gap-2 mb-2">
            <span className="text-sm text-gray-600">Mastery:</span>
            <div className="flex-1 h-2 bg-gray-200 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${color.bg}`}
                style={{ width: `${percentage}%` }}
              />
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-600">Target:</span>
            <span className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full border ${diffBadge.bg} ${diffBadge.text} ${diffBadge.border}`}>
              <TrendingUp className="w-3 h-3" />
              {targetDifficulty.charAt(0).toUpperCase() + targetDifficulty.slice(1)} Difficulty
            </span>
          </div>
        </div>
      </div>

      {showAdaptingMessage && (
        <p className="text-xs text-gray-500 mt-3">
          Questions are tailored to your current proficiency level
        </p>
      )}
    </div>
  );
}
