/**
 * Skeleton loading components for professional loading states.
 */

import { Network, BarChart3 } from 'lucide-react';

export function GraphSkeleton() {
  return (
    <div className="h-[600px] bg-gradient-to-br from-gray-50 to-gray-100 rounded-lg border border-gray-200 animate-pulse">
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <div className="relative">
            <Network className="w-20 h-20 text-gray-300 mx-auto mb-4" />
            {/* Animated pulse rings */}
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="w-24 h-24 rounded-full border-2 border-gray-200 animate-ping opacity-20" />
            </div>
          </div>
          <div className="h-5 w-48 bg-gray-200 rounded mx-auto mb-3" />
          <div className="h-4 w-36 bg-gray-200 rounded mx-auto" />
        </div>
      </div>
    </div>
  );
}

export function StatsSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-6 sm:grid-cols-3">
      {[1, 2, 3].map((i) => (
        <div
          key={i}
          className="bg-white p-6 rounded-lg shadow-md border border-gray-200 animate-pulse"
        >
          <div className="w-14 h-14 bg-gray-200 rounded-lg mb-4" />
          <div className="h-8 w-20 bg-gray-200 rounded mb-2" />
          <div className="h-4 w-32 bg-gray-200 rounded mb-1" />
          <div className="h-3 w-24 bg-gray-200 rounded" />
        </div>
      ))}
    </div>
  );
}

export function ChatMessageSkeleton() {
  return (
    <div className="flex justify-start">
      <div className="max-w-3xl rounded-lg px-6 py-4 bg-white border border-gray-200 shadow-sm animate-pulse">
        <div className="space-y-3">
          <div className="h-4 w-full bg-gray-200 rounded" />
          <div className="h-4 w-5/6 bg-gray-200 rounded" />
          <div className="h-4 w-4/6 bg-gray-200 rounded" />
        </div>
        <div className="mt-4 pt-3 border-t border-gray-100">
          <div className="h-3 w-40 bg-gray-200 rounded" />
        </div>
      </div>
    </div>
  );
}

export function QuizSkeleton() {
  return (
    <div className="max-w-2xl mx-auto animate-pulse">
      {/* Progress bar */}
      <div className="mb-6 flex justify-between items-center">
        <div className="h-4 w-32 bg-gray-200 rounded" />
        <div className="h-4 w-20 bg-gray-200 rounded" />
      </div>

      {/* Question card */}
      <div className="bg-white rounded-xl shadow-lg overflow-hidden border border-gray-200">
        <div className="p-6 md:p-8">
          <div className="h-6 w-full bg-gray-200 rounded mb-6" />
          <div className="h-6 w-3/4 bg-gray-200 rounded mb-8" />

          {/* Options */}
          <div className="space-y-3">
            {[1, 2, 3, 4].map((i) => (
              <div
                key={i}
                className="w-full p-4 rounded-lg border-2 border-gray-200"
              >
                <div className="h-5 w-full bg-gray-200 rounded" />
              </div>
            ))}
          </div>
        </div>

        {/* Action button area */}
        <div className="p-6 border-t bg-gray-50 flex justify-end">
          <div className="h-10 w-32 bg-gray-200 rounded-md" />
        </div>
      </div>
    </div>
  );
}

export function LearningPathSkeleton() {
  return (
    <div className="relative animate-pulse">
      {/* Vertical timeline line */}
      <div className="absolute left-8 top-0 bottom-0 w-0.5 bg-gray-200" />

      {[1, 2, 3, 4].map((i) => (
        <div key={i} className="relative pl-20 pb-8">
          {/* Node indicator */}
          <div className="absolute left-6 w-4 h-4 rounded-full bg-gray-200" />

          {/* Concept card */}
          <div className="p-4 rounded-lg border border-gray-200 bg-white">
            <div className="h-5 w-40 bg-gray-200 rounded mb-3" />
            <div className="h-2 w-full bg-gray-200 rounded mb-2" />
            <div className="h-3 w-24 bg-gray-200 rounded" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="animate-pulse">
      {/* Header */}
      <div className="grid grid-cols-4 gap-4 pb-4 border-b border-gray-200">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-4 bg-gray-200 rounded" />
        ))}
      </div>

      {/* Rows */}
      {Array.from({ length: rows }).map((_, rowIdx) => (
        <div
          key={rowIdx}
          className="grid grid-cols-4 gap-4 py-4 border-b border-gray-100"
        >
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-4 bg-gray-200 rounded" />
          ))}
        </div>
      ))}
    </div>
  );
}
