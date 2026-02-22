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

