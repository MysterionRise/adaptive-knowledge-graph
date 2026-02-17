'use client';

import { useEffect, useState } from 'react';
import { ChevronDown, BookOpen } from 'lucide-react';
import { apiClient } from '@/lib/api-client';
import type { SubjectSummary } from '@/lib/types';
import { useAppStore } from '@/lib/store';

interface SubjectPickerProps {
  className?: string;
}

export default function SubjectPicker({ className = '' }: SubjectPickerProps) {
  const [subjects, setSubjects] = useState<SubjectSummary[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  const { currentSubject, setCurrentSubject, subjectTheme, loadSubjectTheme } = useAppStore();

  // Load subjects on mount
  useEffect(() => {
    async function loadSubjects() {
      setIsLoading(true);
      try {
        const response = await apiClient.getSubjects();
        setSubjects(response.subjects);

        // Set default subject if not already set
        if (!currentSubject) {
          setCurrentSubject(response.default_subject);
          await loadSubjectTheme(response.default_subject);
        }
      } catch (error) {
        console.error('Failed to load subjects:', error);
      } finally {
        setIsLoading(false);
      }
    }

    loadSubjects();
  }, [currentSubject, setCurrentSubject, loadSubjectTheme]);

  // Handle subject change
  const handleSubjectChange = async (subjectId: string) => {
    setCurrentSubject(subjectId);
    await loadSubjectTheme(subjectId);
    setIsOpen(false);
  };

  // Get current subject info
  const currentSubjectInfo = subjects.find((s) => s.id === currentSubject);

  // Get color for subject indicator
  const getSubjectColor = (subjectId: string): string => {
    // Use theme color if available, otherwise default colors
    if (subjectTheme && subjectTheme.subject_id === subjectId) {
      return subjectTheme.primary_color;
    }
    // Default colors for subjects (must match subjects.yaml theme.primary_color)
    const defaultColors: Record<string, string> = {
      us_history: '#dc2626',
      biology: '#16a34a',
      economics: '#d97706',
      world_history: '#4f46e5',
    };
    return defaultColors[subjectId] || '#6366f1';
  };

  if (isLoading) {
    return (
      <div className={`flex items-center gap-2 ${className}`}>
        <div className="w-32 h-9 bg-gray-200 animate-pulse rounded-lg"></div>
      </div>
    );
  }

  return (
    <div className={`relative ${className}`}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 px-3 py-2 bg-white border border-gray-200 rounded-lg shadow-sm hover:bg-gray-50 hover:border-gray-300 transition-all"
        aria-haspopup="listbox"
        aria-expanded={isOpen}
      >
        <div
          className="w-3 h-3 rounded-full"
          style={{ backgroundColor: getSubjectColor(currentSubject || '') }}
        />
        <BookOpen className="w-4 h-4 text-gray-500" />
        <span className="text-sm font-medium text-gray-700">
          {currentSubjectInfo?.name || 'Select Subject'}
        </span>
        <ChevronDown
          className={`w-4 h-4 text-gray-400 transition-transform ${isOpen ? 'rotate-180' : ''}`}
        />
      </button>

      {isOpen && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-10"
            onClick={() => setIsOpen(false)}
          />

          {/* Dropdown */}
          <div className="absolute top-full left-0 mt-1 w-64 bg-white border border-gray-200 rounded-lg shadow-lg z-20 py-1 animate-in fade-in slide-in-from-top-1 duration-150">
            {subjects.map((subject) => (
              <button
                key={subject.id}
                onClick={() => handleSubjectChange(subject.id)}
                className={`w-full flex items-center gap-3 px-4 py-2.5 hover:bg-gray-50 transition-colors ${
                  subject.id === currentSubject ? 'bg-gray-50' : ''
                }`}
                role="option"
                aria-selected={subject.id === currentSubject}
              >
                <div
                  className="w-3 h-3 rounded-full flex-shrink-0"
                  style={{ backgroundColor: getSubjectColor(subject.id) }}
                />
                <div className="flex-1 text-left">
                  <div className="text-sm font-medium text-gray-900">
                    {subject.name}
                  </div>
                  <div className="text-xs text-gray-500 line-clamp-1">
                    {subject.description}
                  </div>
                </div>
                {subject.is_default && (
                  <span className="text-xs text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">
                    Default
                  </span>
                )}
                {subject.id === currentSubject && (
                  <div className="w-2 h-2 rounded-full bg-green-500" />
                )}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
